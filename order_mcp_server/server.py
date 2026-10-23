"""EZStore 訂單與客戶唯讀 MCP Server（mcp Python SDK 2.x，Streamable HTTP）。

提供 3 個唯讀工具給 order_agent 呼叫，全部透過 EZStore 後端 REST API 讀取資料：
  get_order_by_number / list_customer_orders / get_quotation_number

設計原則：
- 只讀不寫：本服務只發出 GET 請求。
- 回傳結構化資料（Pydantic model → MCP structuredContent），由 Agent 決定如何呈現；
  每筆訂單／報價單都附上純文字系統連結。
- 後端沒有 order_number 篩選參數（未知參數會被忽略、回傳全部訂單），
  所以依編號查詢是「分頁列出後在本服務比對」。
- 後端錯誤一律轉成中文 ToolError，不把 traceback 丟給 Agent。
"""

import os

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))
API_BASE = f"{BACKEND_URL}/api/v1"
PAGE_SIZE = 100

mcp = MCPServer("ezstore-order")

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_client = httpx.AsyncClient(base_url=API_BASE, timeout=_TIMEOUT)


# ---------------------------------------------------------------------------
# Result models (structured tool output)
# ---------------------------------------------------------------------------


class OrderItem(BaseModel):
    product_name: str
    unit_price: float
    quantity: int
    subtotal: float


class Order(BaseModel):
    id: int
    order_number: str
    customer_id: int
    customer_name: str
    status: str
    total_price: float
    notes: str
    quotation_id: int | None
    created_at: str
    items: list[OrderItem]
    link: str


class OrderSummary(BaseModel):
    id: int
    order_number: str
    status: str
    total_price: float
    created_at: str
    link: str


class Customer(BaseModel):
    id: int
    name: str
    level: str


class CustomerOrders(BaseModel):
    """result="ok": orders of `customer`; result="ambiguous": ask which of `candidates`."""

    result: str
    customer: Customer | None = None
    orders: list[OrderSummary] = []
    candidates: list[Customer] = []


class QuotationRef(BaseModel):
    quotation_id: int
    quotation_number: str
    status: str
    link: str


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _get(path: str, **params) -> dict:
    try:
        resp = await _client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            raise ToolError("找不到資料") from e
        raise ToolError(f"後端回應 {status}：{e.response.text[:200]}") from e
    except httpx.TimeoutException as e:
        raise ToolError("後端服務逾時，請稍後再試") from e
    except httpx.TransportError as e:
        raise ToolError(f"無法連線後端服務：{e}") from e


async def _all_pages(path: str, **params) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        data = await _get(path, page=page, page_size=PAGE_SIZE, **params)
        batch = data.get("data") or []
        rows.extend(batch)
        if not batch or page * PAGE_SIZE >= data.get("total", 0):
            return rows
        page += 1


def _order_link(order_id: int) -> str:
    return f"{FRONTEND_URL}/orders/{order_id}"


def _quotation_link(quotation_id: int) -> str:
    return f"{FRONTEND_URL}/quotations/{quotation_id}"


def _customer(c: dict) -> Customer:
    return Customer(id=c["id"], name=c["name"], level=c.get("level", ""))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_order_by_number(order_number: str) -> Order:
    """依訂單編號查詢訂單詳細資訊（客戶、狀態、總價、品項、備註、來源報價單 ID）。

    Args:
        order_number: 訂單編號，例如 ORD-20260118-001
    """
    wanted = order_number.strip().upper()
    match = next(
        (o for o in await _all_pages("/orders") if o["order_number"] == wanted), None
    )
    if match is None:
        raise ToolError(f"找不到訂單編號 {wanted}")
    o = await _get(f"/orders/{match['id']}")
    return Order(
        id=o["id"],
        order_number=o["order_number"],
        customer_id=o["customer_id"],
        customer_name=(o.get("customer") or {}).get("name", ""),
        status=o["status"],
        total_price=float(o["total_price"]),
        notes=o.get("notes") or "",
        quotation_id=o.get("quotation_id"),
        created_at=o["created_at"],
        items=[
            OrderItem(
                product_name=i["product_name"],
                unit_price=float(i["unit_price"]),
                quantity=i["quantity"],
                subtotal=float(i["subtotal"]),
            )
            for i in o.get("items") or []
        ],
        link=_order_link(o["id"]),
    )


@mcp.tool()
async def list_customer_orders(customer_name: str) -> CustomerOrders:
    """依客戶名稱列出該客戶的所有訂單。名稱對到多位客戶時回傳 result="ambiguous" 與候選名單。

    Args:
        customer_name: 客戶名稱（可部分比對），例如「史塔克工業」
    """
    name = customer_name.strip()
    customers = await _all_pages("/customers", search=name)
    if not customers:
        raise ToolError(f"找不到客戶名稱包含「{name}」的客戶")
    exact = [c for c in customers if c["name"] == name]
    if len(exact) == 1:
        customer = exact[0]
    elif len(customers) == 1:
        customer = customers[0]
    else:
        return CustomerOrders(
            result="ambiguous", candidates=[_customer(c) for c in customers]
        )
    orders = await _all_pages("/orders", customer_id=customer["id"])
    return CustomerOrders(
        result="ok",
        customer=_customer(customer),
        orders=[
            OrderSummary(
                id=o["id"],
                order_number=o["order_number"],
                status=o["status"],
                total_price=float(o["total_price"]),
                created_at=o["created_at"],
                link=_order_link(o["id"]),
            )
            for o in orders
        ],
    )


@mcp.tool()
async def get_quotation_number(quotation_id: int) -> QuotationRef:
    """依報價單 ID 查詢報價單編號（訂單只記錄 quotation_id）。

    Args:
        quotation_id: 報價單 ID，例如 8
    """
    try:
        q = await _get(f"/quotations/{quotation_id}")
    except ToolError as e:
        raise ToolError(f"找不到報價單 ID {quotation_id}") from e
    return QuotationRef(
        quotation_id=q["id"],
        quotation_number=q["quotation_number"],
        status=q["status"],
        link=_quotation_link(q["id"]),
    )


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
        streamable_http_path="/mcp",
    )
