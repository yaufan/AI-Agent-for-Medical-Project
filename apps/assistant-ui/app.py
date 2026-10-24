"""Company M internal assistant — Chainlit demo UI.

    chainlit run apps/assistant-ui/app.py
    # with a model (any OpenAI-compatible server); without these it uses the fixed workflow
    ASSISTANT_LLM_BASE_URL=http://localhost:8000/v1 ASSISTANT_LLM_MODEL=qwen3.8-27b-q8 chainlit run ...

The chat profile stands in for sign-in: picking a profile is picking who you are. In production the
identity and groups come from the identity provider, never from a menu.
"""
from __future__ import annotations

import sys
from pathlib import Path

import chainlit as cl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend import Backend, Table, describe_draft, is_tainted, markdown_table, short_json  # noqa: E402

BACKEND = Backend.from_env()

STARTERS = {
    "qa_lin": ["哪些醫院有 C-320 這款 CT？", "醫院F 有哪些和 C-320 相關的客訴？有沒有連到 CAPA？",
               "醫院F 的 C-320 客訴還沒連到 CAPA，請幫我起草 CAPA，關聯這些客訴", "CAPA-2026-007 現在的狀態是什麼？已經逾期了嗎？"],
    "svc_wang": ["SSD 批號 SSD-S1-L2508 裝在哪些主機上？哪些還沒故障？", "醫院E 的推論主機現在跑哪個軟體版本？",
                 "站點新增 CT 掃描儀時，安裝程序要求做哪些檢查？", "GPU G1 的最後採購日是哪一天？"],
    "rd_chen": ["NoduleAssist 2.0 預計什麼時候提出 510(k)？", "GPU G1 停產後改用 G2，模型要做哪些再驗證？"],
    "ra_huang": ["OEB 最近有哪些 510(k)？", "OEB 有沒有召回紀錄？", "NoduleAssist 2.0 預計什麼時候提出 510(k)？"],
    "contractor_lee": ["NoduleAssist 2.0 預計什麼時候提出 510(k)？", "站點新增 CT 掃描儀時，安裝程序要求做哪些檢查？"],
    "qa_mgr_chou": ["待核准", "稽核紀錄"],
    "ops_mgr_tsai": ["營運總覽", "2026-09 QC 拒收率超過 5% 的站點有哪些？", "每個軟體版本目前裝在幾台主機上？",
                     "哪些 CAPA 已經過了到期日但還沒結案？"],
}


def figure(t: Table):
    """Plotly figure for a bar or line table; None for plain tables."""
    import plotly.graph_objects as go

    if t.chart == "bar":
        fig = go.Figure(go.Bar(x=[str(r[0]) for r in t.rows], y=[r[1] for r in t.rows]))
        fig.update_layout(xaxis_title=t.columns[0], yaxis_title=t.columns[1])
    elif t.chart == "line":
        m = t.columns.index("month")
        nums = [i for i in range(len(t.columns)) if i != m and all(isinstance(r[i], (int, float)) for r in t.rows)]
        labels = [i for i in range(len(t.columns)) if i not in nums and i != m]
        fig = go.Figure()
        if labels:  # one line per label, first numeric column as the value
            for key in sorted({r[labels[0]] for r in t.rows}):
                pts = [r for r in t.rows if r[labels[0]] == key]
                fig.add_trace(go.Scatter(x=[r[m] for r in pts], y=[r[nums[0]] for r in pts], mode="lines", name=str(key)))
            fig.update_layout(yaxis_title=t.columns[nums[0]])
        else:
            for i in nums:
                fig.add_trace(go.Scatter(x=[r[m] for r in t.rows], y=[r[i] for r in t.rows], mode="lines",
                                         name=t.columns[i]))
    else:
        return None
    fig.update_layout(title=t.title, height=360, margin=dict(l=40, r=20, t=50, b=40))
    return fig


async def show_table(t: Table):
    if t.sql:
        async with cl.Step(name="SQL（唯讀）", type="tool", show_input=False) as step:
            step.output = f"```sql\n{t.sql}\n```"
    if t.error:
        await cl.Message(f"**{t.title}**\n\n⛔ {t.error}").send()
        return
    fig = figure(t)
    elements = [cl.Plotly(name="chart", figure=fig, display="inline")] if fig is not None else []
    table = markdown_table(t.columns, t.rows) if t.chart == "table" or len(t.rows) <= 12 else ""
    extra = f"\n\n*{t.seconds} 秒*" if t.seconds else ""
    await cl.Message(f"**{t.title}**（{len(t.rows)} 列）\n\n{table}{extra}", elements=elements).send()


def md(text: str) -> str:
    return text.replace("\n", "  \n")


@cl.set_chat_profiles
async def chat_profiles(current_user=None):
    return [cl.ChatProfile(name=user, display_name=f"{role}（{user}）",
                           markdown_description=f"以 **{role}** 身分登入；可讀群組：{', '.join(sorted(BACKEND.groups.groups(user)))}",
                           default=(user == "qa_lin"))
            for user, role in BACKEND.users.items()]


def current_user() -> str:
    return cl.user_session.get("chat_profile") or "qa_lin"


@cl.on_chat_start
async def start():
    user = current_user()
    await cl.Message(md(
        f"你目前是 **{BACKEND.users[user]}（{user}）**，可讀群組：{', '.join(sorted(BACKEND.groups.groups(user)))}。\n"
        f"回答方式：{BACKEND.mode}。\n"
        "寫入動作（CAPA、工單、通知）只會產生草稿，要由品保主管在「待核准」核准後才生效。\n"
        "（示範用：切換左上角的身分就是換人登入；正式環境身分來自公司帳號。資料全部是合成資料，非醫療用途。）\n\n"
        "可以直接點下面的範例問題："),
        actions=[cl.Action(name="ask", payload={"q": q}, label=q) for q in STARTERS.get(user, [])]).send()
    if BACKEND.pending_for(user):
        await show_pending(user)


async def show_pending(user: str):
    pending = BACKEND.pending_for(user)
    if not pending:
        await cl.Message("目前沒有你可以核准的草稿。").send()
        return
    for d in pending:
        actions = [cl.Action(name="reject", payload={"draft_id": d["draft_id"]}, label="退回")]
        if is_tainted(d):
            actions.insert(0, cl.Action(name="approve", payload={"draft_id": d["draft_id"], "ack": True},
                                        label="已確認第三方文字，核准"))
        else:
            actions.insert(0, cl.Action(name="approve", payload={"draft_id": d["draft_id"], "ack": False}, label="核准"))
        await cl.Message(md(describe_draft(d)), actions=actions).send()


async def show_audit():
    rows = BACKEND.drafts.audit()[-20:]
    if not rows:
        await cl.Message("稽核紀錄是空的。").send()
        return
    table = "| # | 時間 | 人員 | 動作 | 內容 |\n|---|---|---|---|---|\n" + "\n".join(
        f"| {r['seq']} | {r['ts']} | {r['actor']} | {r['action']} | {r['detail']} |" for r in rows)
    await cl.Message("最近 20 筆稽核紀錄（只能新增，不能修改或刪除）：\n\n" + table).send()


@cl.action_callback("approve")
async def on_approve(action: cl.Action):
    ok, msg = BACKEND.decide(current_user(), action.payload["draft_id"], True, action.payload.get("ack", False))
    await cl.Message(("✅ " if ok else "⛔ ") + msg).send()
    if ok:
        await action.remove()


@cl.action_callback("reject")
async def on_reject(action: cl.Action):
    ok, msg = BACKEND.decide(current_user(), action.payload["draft_id"], False)
    await cl.Message(("↩️ " if ok else "⛔ ") + msg).send()
    if ok:
        await action.remove()


@cl.action_callback("ask")
async def on_example(action: cl.Action):
    await cl.Message(content=action.payload["q"], author=current_user(), type="user_message").send()
    await handle(action.payload["q"])


@cl.on_message
async def on_message(message: cl.Message):
    await handle(message.content.strip())


async def handle(text: str):
    user = current_user()
    if text in ("待核准", "/pending"):
        await show_pending(user)
        return
    if text in ("稽核紀錄", "/audit"):
        await show_audit()
        return
    if BACKEND.can_query(user):
        if text in ("營運總覽", "/dashboard"):
            for t in await cl.make_async(BACKEND.dashboard)(user):
                await show_table(t)
        else:
            await show_table(await cl.make_async(BACKEND.ask_sql)(user, text))
        return

    turn = await cl.make_async(BACKEND.ask)(user, text)
    for c in turn.calls:
        status = "✅" if c["ok"] else f"⛔ {c['error']}"
        async with cl.Step(name=f"{c['tool']}　{status}", type="tool", show_input="json") as step:
            step.input = c["args"]
            note = f"（{c['ms']} ms）"
            if c.get("tainted_fields"):
                note += f"\n⚠️ 草稿欄位 {', '.join(c['tainted_fields'])} 的文字來自客戶或外部資料，已標記"
            step.output = note + "\n\n```json\n" + short_json(c["result"]) + "\n```"

    body = md(turn.answer)
    if turn.sources:
        body += "\n\n**出處**：" + "、".join(turn.sources)
    for d in turn.drafts:
        body += f"\n\n📝 已建立草稿 **{d['draft_id']}**（{d['kind']}），尚未生效，等待有權限的主管核准。"
    body += f"\n\n*{turn.mode}・{len(turn.calls)} 次工具呼叫・{turn.seconds} 秒*"
    await cl.Message(body).send()
