import base64
import json
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
from telegram.constants import ParseMode

from src.agent.intent_parser import IntentParser
from src.agent.orchestrator import Orchestrator
from src.security.auth import AuthManager
from src.utils.logger import logger

# ── Emoji ──
EMOJI = {
    "robot": "🤖", "create": "📦", "list": "📋", "delete": "🗑",
    "stats": "📊", "health": "🔍", "help": "ℹ️", "back": "🔙",
    "refresh": "🔄", "prev": "⬅️", "next": "➡️", "ok": "✅",
    "fail": "❌", "warn": "⚠️", "active": "🟢", "error": "🔴",
    "creating": "🟡", "share": "🔗", "copy": "📝", "confirm": "✔️",
    "cancel": "✖️", "detail": "🔎", "vless": "🔹", "vmess": "🔸",
    "trojan": "🔺", "ss": "🟣", "socks5": "🟠", "http": "🟤",
}

PROTO_EMOJI = {
    "vless": "🔹", "vmess": "🔸", "trojan": "🔺",
    "shadowsocks": "🟣", "socks5": "🟠", "http": "🟤",
}

STATUS_EMOJI = {"active": "🟢", "error": "🔴", "creating": "🟡"}

# ── Keyboard Builders ──

def _main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['create']} 创建代理", callback_data="menu_create")],
        [InlineKeyboardButton(f"{EMOJI['list']} 代理列表", callback_data="menu_list:0"),
         InlineKeyboardButton(f"{EMOJI['stats']} 统计信息", callback_data="menu_stats")],
        [InlineKeyboardButton(f"{EMOJI['health']} 健康检查", callback_data="menu_health"),
         InlineKeyboardButton(f"{EMOJI['help']} 帮助", callback_data="menu_help")],
    ])


def _create_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['create']} 1个 VLESS + Shadowsocks", callback_data="create:1:vless,shadowsocks")],
        [InlineKeyboardButton(f"{EMOJI['create']} 3个 全部协议", callback_data="create:3:all")],
        [InlineKeyboardButton(f"{EMOJI['create']} 5个 VLESS", callback_data="create:5:vless")],
        [InlineKeyboardButton(f"{EMOJI['create']} 10个 SOCKS5", callback_data="create:10:socks5")],
        [InlineKeyboardButton(f"{EMOJI['back']} 返回", callback_data="menu_main")],
    ])


def _proxy_list_keyboard(proxies: list, page: int = 0, per_page: int = 5):
    total = len(proxies)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_items = proxies[start:start + per_page]

    buttons = []
    for p in page_items:
        status_icon = STATUS_EMOJI.get(p["status"], "⚪")
        proto_short = ",".join(p["protocols"][:2])
        if len(p["protocols"]) > 2:
            proto_short += f"+{len(p['protocols'])-2}"
        label = f"{status_icon} #{p['id']} {p['ipv6_addr'][-12:]} ({proto_short})"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"proxy_detail:{p['id']}"),
            InlineKeyboardButton(f"{EMOJI['delete']} 删", callback_data=f"delete_confirm:{p['id']}"),
        ])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(f"{EMOJI['prev']} 上一页", callback_data=f"menu_list:{page-1}"))
    nav_row.append(InlineKeyboardButton(f"{EMOJI['refresh']} 刷新", callback_data=f"menu_list:{page}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(f"下一页 {EMOJI['next']}", callback_data=f"menu_list:{page+1}"))
    buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(f"{EMOJI['back']} 主菜单", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


def _confirm_delete_keyboard(proxy_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['confirm']} 确认删除", callback_data=f"delete_exec:{proxy_id}")],
        [InlineKeyboardButton(f"{EMOJI['cancel']} 取消", callback_data=f"proxy_detail:{proxy_id}")],
    ])


def _proxy_detail_keyboard(proxy_id: int, list_page: int = 0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['share']} 分享链接", callback_data=f"show_links:{proxy_id}")],
        [InlineKeyboardButton(f"{EMOJI['health']} 检测连通性", callback_data=f"proxy_check:{proxy_id}"),
         InlineKeyboardButton(f"{EMOJI['delete']} 删除", callback_data=f"delete_confirm:{proxy_id}")],
        [InlineKeyboardButton(f"{EMOJI['back']} 返回列表", callback_data=f"menu_list:{list_page}")],
    ])


def _stats_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['refresh']} 刷新", callback_data="menu_stats"),
         InlineKeyboardButton(f"{EMOJI['health']} 执行健康检查", callback_data="menu_health")],
        [InlineKeyboardButton(f"{EMOJI['back']} 主菜单", callback_data="menu_main")],
    ])


def _back_only_keyboard(target: str = "menu_main"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['back']} 返回", callback_data=target)],
    ])


# ── Formatters ──

def _fmt_header(title: str) -> str:
    return f"{EMOJI['robot']} *IPv666* ── {title}"

def _fmt_share_links(proxy: dict) -> str:
    lines = [f"*代理 #{proxy['id']}* ── 分享链接\n"]
    for proto, link in proxy.get("share_links", {}).items():
        p_emoji = PROTO_EMOJI.get(proto, "")
        short_link = link[:90] + "..." if len(link) > 90 else link
        lines.append(f"{p_emoji} *{proto.upper()}*:\n`{short_link}`\n")
    return "\n".join(lines)

def _proto_tags(protocols: list) -> str:
    return " ".join(f"{PROTO_EMOJI.get(p,'')}{p}" for p in protocols)


# ── Main Bot Class ──

class TelegramBot:
    def __init__(self, token: str, orchestrator: Orchestrator, intent_parser: IntentParser,
                 auth_manager: AuthManager):
        self.token = token
        self.orchestrator = orchestrator
        self.intent_parser = intent_parser
        self.auth_manager = auth_manager
        self.app: Application = None
        self._pending_create: dict[str, dict] = {}

    def build_app(self) -> Application:
        self.app = Application.builder().token(self.token).build()
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("create", self._cmd_create))
        self.app.add_handler(CommandHandler("list", self._cmd_list))
        self.app.add_handler(CommandHandler("delete", self._cmd_delete))
        self.app.add_handler(CommandHandler("stats", self._cmd_stats))
        self.app.add_handler(CommandHandler("menu", self._cmd_start))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self.app.add_error_handler(self._error_handler)
        return self.app

    # ── Auth ──

    async def _check_auth(self, update: Update) -> bool:
        user_id = str(update.effective_user.id)
        if not await self.auth_manager.is_authorized(user_id):
            if update.callback_query:
                await update.callback_query.answer("无访问权限，请联系管理员。", show_alert=True)
            elif update.message:
                await update.message.reply_text(
                    f"{EMOJI['fail']} 无访问权限，请联系管理员添加白名单。"
                )
            return False
        return True

    # ── Command Handlers ──

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        text = (
            f"{_fmt_header('控制面板')}\n\n"
            f"*IPv6 站群代理管理器*\n"
            f"通过 AI 自然语言管理数万个 IPv6 代理。\n\n"
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_"
        )
        await update.message.reply_text(
            text, reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        text = (
            f"{_fmt_header('帮助')}\n\n"
            f"• *直接聊天*，用中文或英文都行\n"
            f"• 点击下方菜单按钮快速操作\n"
            f"• 也可以输入指令：\n"
            f"  `/create 5 vless` \\- 创建代理\n"
            f"  `/list` \\- 查看所有代理\n"
            f"  `/delete 3` \\- 删除代理\n"
            f"  `/stats` \\- 查看统计\n\n"
            f"*支持协议:* VLESS \\| VMess \\| Trojan \\| Shadowsocks \\| SOCKS5 \\| HTTP"
        )
        await update.message.reply_text(
            text, reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        args = context.args
        if not args:
            await update.message.reply_text(
                f"{_fmt_header('创建代理')}\n\n选择快捷预设，或输入自定义指令：\n`create 5 vless shadowsocks`",
                reply_markup=_create_menu_keyboard(), parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            count = int(args[0])
        except ValueError:
            count = 1
        protocols = args[1:] if len(args) > 1 else ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]
        protocols = self._normalize_protocols(protocols)
        await self._do_create(update, count, protocols)

    async def _cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await self._show_proxy_list(update, page=0)

    async def _cmd_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        args = context.args
        if not args:
            await update.message.reply_text(
                f"{_fmt_header('删除代理')}\n\n用法：`/delete <编号>`\n或从列表菜单中浏览删除。",
                reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            proxy_id = int(args[0])
        except ValueError:
            await update.message.reply_text(f"{EMOJI['fail']} 编号无效，请输入数字。")
            return
        success = await self.orchestrator.delete_proxy(proxy_id=proxy_id)
        if success:
            await update.message.reply_text(
                f"{EMOJI['ok']} 代理 #{proxy_id} 已删除。",
                reply_markup=_main_menu_keyboard(),
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['fail']} 删除代理 #{proxy_id} 失败。",
                reply_markup=_main_menu_keyboard(),
            )

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await self._show_stats(update)

    # ── Callback Handler ──

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not await self._check_auth(update):
            return

        data = query.data
        user_id = str(update.effective_user.id)

        try:
            # ── 主菜单 ──
            if data == "menu_main":
                text = f"{_fmt_header('控制面板')}\n\n_{datetime.now().strftime('%Y-%m-%d %H:%M')}_"
                await query.edit_message_text(text, reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

            elif data == "menu_create":
                text = f"{_fmt_header('创建代理')}\n\n选择快捷预设，或输入自定义指令：\n`create 5 vless ss`"
                await query.edit_message_text(text, reply_markup=_create_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

            elif data == "menu_stats":
                await self._show_stats(update, edit=True)

            elif data == "menu_health":
                await self._do_health_check(update, edit=True)

            elif data == "menu_help":
                text = (
                    f"{_fmt_header('帮助')}\n\n"
                    f"• *直接聊天*，用中文或英文\n"
                    f"• 或输入指令：`/create 5 vless`\n"
                    f"• 协议：VLESS VMess Trojan Shadowsocks SOCKS5 HTTP\n\n"
                    f"*快捷预设：*"
                )
                await query.edit_message_text(text, reply_markup=_create_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

            # ── 代理列表（分页） ──
            elif data.startswith("menu_list:"):
                page = int(data.split(":")[1])
                await self._show_proxy_list(update, page=page, edit=True)

            # ── 创建预设 ──
            elif data.startswith("create:"):
                parts = data.split(":")
                count = int(parts[1])
                proto_str = parts[2]
                if proto_str == "all":
                    protocols = ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]
                else:
                    protocols = proto_str.split(",")
                proto_tags = _proto_tags(protocols)
                msg = await query.edit_message_text(
                    f"{EMOJI['create']} 正在创建 {count} 个代理，协议：{proto_tags}...",
                )
                created_count, results = await self.orchestrator.create_proxies(count, protocols)
                await self._show_create_result(msg, created_count, results)

            # ── 代理详情 ──
            elif data.startswith("proxy_detail:"):
                proxy_id = int(data.split(":")[1])
                await self._show_proxy_detail(update, proxy_id, edit=True)

            # ── 分享链接 ──
            elif data.startswith("show_links:"):
                proxy_id = int(data.split(":")[1])
                proxies = await self.orchestrator.list_proxies()
                proxy = next((p for p in proxies if p["id"] == proxy_id), None)
                if not proxy:
                    await query.edit_message_text(
                        f"{EMOJI['fail']} 代理 #{proxy_id} 不存在。",
                        reply_markup=_back_only_keyboard(),
                    )
                    return
                text = _fmt_share_links(proxy)
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} 返回代理详情", callback_data=f"proxy_detail:{proxy_id}")],
                    [InlineKeyboardButton(f"{EMOJI['list']} 代理列表", callback_data="menu_list:0")],
                ])
                await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

            # ── 删除确认 ──
            elif data.startswith("delete_confirm:"):
                proxy_id = int(data.split(":")[1])
                text = f"{EMOJI['warn']} *确认删除代理 #{proxy_id}？*\n\n此操作不可撤销。"
                await query.edit_message_text(
                    text, reply_markup=_confirm_delete_keyboard(proxy_id), parse_mode=ParseMode.MARKDOWN,
                )

            # ── 执行删除 ──
            elif data.startswith("delete_exec:"):
                proxy_id = int(data.split(":")[1])
                success = await self.orchestrator.delete_proxy(proxy_id=proxy_id)
                if success:
                    text = f"{EMOJI['ok']} 代理 #{proxy_id} 已成功删除。"
                else:
                    text = f"{EMOJI['fail']} 删除代理 #{proxy_id} 失败。"
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{EMOJI['list']} 返回列表", callback_data="menu_list:0")],
                        [InlineKeyboardButton(f"{EMOJI['back']} 主菜单", callback_data="menu_main")],
                    ]),
                )

            # ── 单个代理连通性检测 ──
            elif data.startswith("proxy_check:"):
                proxy_id = int(data.split(":")[1])
                from src.db.database import get_db
                from src.db.models import Proxy as ProxyModel
                from src.proxy.verifier import ProxyVerifier
                db = await get_db()
                try:
                    cursor = await db.execute("SELECT * FROM proxies WHERE id=?", (proxy_id,))
                    row = await cursor.fetchone()
                    if not row:
                        await query.edit_message_text(
                            f"{EMOJI['fail']} 代理 #{proxy_id} 不存在。",
                            reply_markup=_back_only_keyboard(),
                        )
                        return
                    cols = [d[0] for d in cursor.description]
                    d = {cols[i]: row[i] for i in range(len(row))}
                    proxy = ProxyModel(
                        id=d["id"], ipv6_addr=d["ipv6_addr"], base_port=d["base_port"],
                        protocols=json.loads(d["protocols"]) if d["protocols"] else [],
                        cred_uuids=json.loads(d["cred_uuids"]) if d.get("cred_uuids") else {},
                        cred_passwords=json.loads(d["cred_passwords"]) if d.get("cred_passwords") else {},
                    )
                finally:
                    await db.close()

                verifier = ProxyVerifier()
                ok = await verifier.verify(proxy, timeout=5)
                status = f"{EMOJI['ok']} 可连接" if ok else f"{EMOJI['fail']} 不可达"
                text = (
                    f"*代理 #{proxy_id}* 连通性检测\n\n"
                    f"{status}\n"
                    f"IPv6: `{d['ipv6_addr']}`\n"
                    f"端口: `{d['base_port']}`"
                )
                await query.edit_message_text(
                    text, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"{EMOJI['back']} 返回", callback_data=f"proxy_detail:{proxy_id}")],
                    ]),
                )

            else:
                await query.edit_message_text(
                    f"{EMOJI['warn']} 未知操作：{data}",
                    reply_markup=_main_menu_keyboard(),
                )

        except Exception as e:
            logger.error(f"回调处理错误 [{data}]: {e}")
            try:
                await query.edit_message_text(
                    f"{EMOJI['fail']} 发生错误，请重试。",
                    reply_markup=_main_menu_keyboard(),
                )
            except Exception:
                pass

    # ── 自然语言消息处理 ──

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        message = update.message.text
        logger.info(f"收到消息 from {update.effective_user.id}: {message}")

        status_msg = await update.message.reply_text(f"{EMOJI['robot']} 处理中...")

        intent = await self.intent_parser.parse(message)

        try:
            if intent["action"] == "create":
                count = intent.get("count", 1)
                protocols = intent.get("protocols", ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"])
                purpose = intent.get("purpose", "")
                created_count, results = await self.orchestrator.create_proxies(count, protocols, purpose)
                await self._show_create_result(status_msg, created_count, results)

            elif intent["action"] == "delete":
                proxy_id = intent.get("target_id")
                ipv6_addr = intent.get("target_ip")
                if not proxy_id and not ipv6_addr:
                    await status_msg.edit_text(
                        f"{EMOJI['warn']} 请指定代理编号。\n例如：`删除代理 3`",
                        parse_mode=ParseMode.MARKDOWN, reply_markup=_main_menu_keyboard(),
                    )
                    return
                success = await self.orchestrator.delete_proxy(proxy_id=proxy_id, ipv6_addr=ipv6_addr)
                if success:
                    target = f"#{proxy_id}" if proxy_id else ipv6_addr
                    await status_msg.edit_text(
                        f"{EMOJI['ok']} 代理 {target} 已删除。", reply_markup=_main_menu_keyboard(),
                    )
                else:
                    await status_msg.edit_text(
                        f"{EMOJI['fail']} 代理不存在。", reply_markup=_main_menu_keyboard(),
                    )

            elif intent["action"] == "list":
                proxies = await self.orchestrator.list_proxies()
                if not proxies:
                    await status_msg.edit_text(
                        f"{EMOJI['warn']} 还没有代理。\n创建几个试试：`创建 5 个代理`",
                        parse_mode=ParseMode.MARKDOWN, reply_markup=_create_menu_keyboard(),
                    )
                else:
                    active = sum(1 for p in proxies if p["status"] == "active")
                    error = sum(1 for p in proxies if p["status"] == "error")
                    text = f"{_fmt_header('代理列表')}\n\n共 {len(proxies)} 个（{active} {EMOJI['active']} 活跃，{error} {EMOJI['error']} 异常）\n"
                    await status_msg.edit_text(text, reply_markup=_proxy_list_keyboard(proxies, 0), parse_mode=ParseMode.MARKDOWN)

            elif intent["action"] == "status":
                await self._do_health_check(status_msg, edit=True)

            elif intent["action"] == "help":
                text = (
                    f"{_fmt_header('帮助')}\n\n"
                    f"*快捷预设：*\n"
                    f"使用菜单或自然语言输入：\n"
                    f"• `创建 5 个 vless ss 代理`\n"
                    f"• `查看所有代理`\n"
                    f"• `删除代理 3`\n"
                    f"• `检查健康状态`"
                )
                await status_msg.edit_text(text, reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

            else:
                await status_msg.edit_text(
                    f"{EMOJI['warn']} 没理解你的意思。使用菜单或试试：\n"
                    f"`创建 3 个代理`  |  `列表`  |  `帮助`",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=_main_menu_keyboard(),
                )

        except Exception as e:
            logger.error(f"消息处理错误: {e}")
            await status_msg.edit_text(
                f"{EMOJI['fail']} 出错了：{str(e)[:200]}",
                reply_markup=_main_menu_keyboard(),
            )

    # ── Shared Display Methods ──

    async def _do_create(self, update: Update, count: int, protocols: list):
        proto_tags = _proto_tags(protocols)
        msg = await update.message.reply_text(
            f"{EMOJI['create']} 正在创建 {count} 个代理，协议：{proto_tags}..."
        )
        created_count, results = await self.orchestrator.create_proxies(count, protocols)
        await self._show_create_result(msg, created_count, results)

    async def _show_create_result(self, msg, created_count: int, results: list):
        if created_count == 0:
            await msg.edit_text(
                f"{EMOJI['fail']} 创建失败。\n服务器可能已用完 IPv6 地址或端口。",
                reply_markup=_main_menu_keyboard(),
            )
            return

        lines = [f"{EMOJI['ok']} *成功创建 {created_count} 个代理*\n"]
        for r in results[:5]:
            lines.append(f"\n{STATUS_EMOJI.get(r['status'], '')} *代理 #{r['id']}*")
            lines.append(f"`{r['ipv6_addr']}`")
            lines.append(f"{_proto_tags(r['protocols'])}")

        if created_count > 5:
            lines.append(f"\n_... 还有 {created_count - 5} 个_")

        kb_buttons = [[InlineKeyboardButton(f"{EMOJI['list']} 查看全部", callback_data="menu_list:0")]]
        if results:
            kb_buttons.append([
                InlineKeyboardButton(f"{EMOJI['detail']} 详情", callback_data=f"proxy_detail:{results[0]['id']}"),
                InlineKeyboardButton(f"{EMOJI['create']} 继续创建", callback_data="menu_create"),
            ])
        kb_buttons.append([InlineKeyboardButton(f"{EMOJI['back']} 主菜单", callback_data="menu_main")])

        await msg.edit_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode=ParseMode.MARKDOWN,
        )

    async def _show_proxy_list(self, update, page: int = 0, edit: bool = False):
        proxies = await self.orchestrator.list_proxies()
        if not proxies:
            text = (
                f"{_fmt_header('暂无代理')}\n\n"
                f"还没有创建任何代理。\n"
                f"点击下方按钮开始创建。"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['create']} 创建代理", callback_data="menu_create")],
                [InlineKeyboardButton(f"{EMOJI['back']} 主菜单", callback_data="menu_main")],
            ])
        else:
            active = sum(1 for p in proxies if p["status"] == "active")
            error = sum(1 for p in proxies if p["status"] == "error")
            text = (
                f"{_fmt_header('代理列表')}\n\n"
                f"*{len(proxies)}* 个  |  {EMOJI['active']} *{active}* 活跃  |  {EMOJI['error']} *{error}* 异常\n"
                f"_第 {page + 1} 页_"
            )
            kb = _proxy_list_keyboard(proxies, page)

        if edit:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    async def _show_proxy_detail(self, update, proxy_id: int, edit: bool = False):
        proxies = await self.orchestrator.list_proxies()
        proxy = next((p for p in proxies if p["id"] == proxy_id), None)
        if not proxy:
            text = f"{EMOJI['fail']} 代理 #{proxy_id} 不存在。"
            kb = _back_only_keyboard("menu_list:0")
        else:
            status = STATUS_EMOJI.get(proxy["status"], "")
            text = (
                f"*代理 #{proxy['id']}*\n\n"
                f"状态：{status} *{proxy['status']}*\n"
                f"IPv6：`{proxy['ipv6_addr']}`\n"
                f"端口：`{proxy['base_port']}`\n"
                f"协议：{_proto_tags(proxy['protocols'])}\n"
                f"创建时间：`{proxy.get('created_at', '未知')}`"
            )
            kb = _proxy_detail_keyboard(proxy_id)
        if edit:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    async def _show_stats(self, update, edit: bool = False):
        stats = await self.orchestrator.get_stats()
        text = (
            f"{_fmt_header('统计信息')}\n\n"
            f"{EMOJI['robot']} *总计：* `{stats.get('total', 0)}`\n"
            f"{EMOJI['active']} 活跃：`{stats.get('active', 0)}`\n"
            f"{EMOJI['error']} 异常：`{stats.get('error', 0)}`\n"
            f"{EMOJI['creating']} 创建中：`{stats.get('creating', 0)}`\n\n"
            f"已分配 IPv6：`{stats.get('allocated_ips', 0)}`\n"
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
        )
        if edit:
            await update.callback_query.edit_message_text(
                text, reply_markup=_stats_keyboard(), parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                text, reply_markup=_stats_keyboard(), parse_mode=ParseMode.MARKDOWN,
            )

    async def _do_health_check(self, update, edit: bool = False):
        msg = update.callback_query.message if edit else update.message
        if edit:
            await update.callback_query.edit_message_text(f"{EMOJI['health']} 正在执行健康检查...")
        else:
            await msg.reply_text(f"{EMOJI['health']} 正在执行健康检查...")

        result = await self.orchestrator.health_check_all()
        stats = await self.orchestrator.get_stats()

        text = (
            f"{_fmt_header('健康检查')}\n\n"
            f"已检查：*{result['checked']}* 个\n"
            f"{EMOJI['ok']} 健康：*{result['healthy']}*\n"
            f"{EMOJI['fail']} 异常：*{result['unhealthy']}*\n\n"
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['refresh']} 刷新", callback_data="menu_health"),
             InlineKeyboardButton(f"{EMOJI['stats']} 统计", callback_data="menu_stats")],
            [InlineKeyboardButton(f"{EMOJI['list']} 代理列表", callback_data="menu_list:0"),
             InlineKeyboardButton(f"{EMOJI['back']} 菜单", callback_data="menu_main")],
        ])
        if edit:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    # ── Protocol Normalization ──

    def _normalize_protocols(self, raw: list[str]) -> list[str]:
        proto_map = {
            "vless": "vless", "vmess": "vmess", "trojan": "trojan",
            "ss": "shadowsocks", "shadowsocks": "shadowsocks",
            "socks5": "socks5", "socks": "socks5",
            "http": "http", "https": "http",
        }
        normalized = []
        seen = set()
        for p in raw:
            p_clean = p.lower().strip()
            mapped = proto_map.get(p_clean, proto_map.get(p_clean.rstrip("s")))
            if mapped and mapped not in seen:
                normalized.append(mapped)
                seen.add(mapped)
        return normalized if normalized else ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]

    # ── Error Handler ──

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Telegram bot error: {context.error}")

    # ── Lifecycle ──

    async def run(self):
        if not self.app:
            self.build_app()
        logger.info("Starting Telegram bot...")
        await self.app.initialize()
        await self.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await self.app.start()

    async def stop(self):
        if self.app:
            try:
                await self.app.updater.stop()
            except RuntimeError:
                pass
            try:
                await self.app.stop()
            except RuntimeError:
                pass
            try:
                await self.app.shutdown()
            except RuntimeError:
                pass
