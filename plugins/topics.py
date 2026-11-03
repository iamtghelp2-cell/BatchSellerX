# iamtghelp - Auto subject-wise topics
# Bot ko forum group me admin banao -> subject topics apne-aap ban jaate hain.
# Files/posts ke naam + caption se subject pehchan kar sahi topic me bheji jaati hain.

import re
import time
import asyncio
import logging
from pyrogram import filters, enums
from shared_client import app
from config import OWNER_ID
from utils.func import db
from utils.subject_keywords import KEYWORDS

logger = logging.getLogger("iamtghelp")
topics_col = db["subject_topics"]

GENERAL = "General"
WEAK = {"Science"}

# Topic naam -> keywords: utils/subject_keywords.py me hain (chapter-wise, English + Hindi).
DEFAULT_SUBJECTS = dict(KEYWORDS)
DEFAULT_SUBJECTS[GENERAL] = []


def _is_forum(chat):
    """Topics wale group ko pehchano (pyrofork me type == FORUM hota hai)."""
    if chat is None:
        return False
    if getattr(chat, "is_forum", None):
        return True
    return getattr(chat, "type", None) == enums.ChatType.FORUM


async def _group_or_forum(_, __, m):
    return bool(m.chat and m.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.FORUM))


group_or_forum = filters.create(_group_or_forum)


def _norm(text):
    return f" {(text or '').lower()} "


def _split_chat_topic(cfg_chat):
    """'-100123/45' -> (-100123, 45); '-100123' -> (-100123, None)"""
    if cfg_chat is None:
        return None, None
    s = str(cfg_chat)
    if "/" in s:
        a, b = s.split("/", 1)
        return int(a), int(b)
    return int(s), None


async def _get_doc(chat_id):
    return await topics_col.find_one({"chat_id": int(chat_id)})


def _kw_hit(kw, t):
    k = kw.lower().strip()
    if not k:
        return False
    if k.isascii():
        pat = r"(?<![a-z0-9])" + re.escape(k) + (r"(?![a-z0-9])" if len(k) <= 3 else "")
        return re.search(pat, t) is not None
    return k in t


def _match_subject(text, subjects):
    """subjects: {name: {"id": topic_id, "kw": [...]}} -> (name, id) ya (None, None)"""
    t = _norm(text)
    best, best_len = None, 0
    # "Science" generic hai (rasayan vigyan, jeev vigyan me bhi aata hai) -> sabse last me check
    for weak_pass in (False, True):
        for name, info in subjects.items():
            if (name in WEAK) != weak_pass:
                continue
            for kw in info.get("kw", []):
                if _kw_hit(kw, t) and len(kw.strip()) > best_len:
                    best, best_len = name, len(kw.strip())
        if best:
            break
    if best:
        return best, subjects[best]["id"]
    g = subjects.get(GENERAL)
    return (GENERAL, g["id"]) if g else (None, None)


_locks = {}
_tried = {}


async def _ensure_topics(chat_id):
    """Topics abhi tak nahi bane to batch ke waqt khud bana deta hai (5 min me ek hi baar try)."""
    chat_id = int(chat_id)
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        doc = await _get_doc(chat_id)
        if doc and doc.get("subjects"):
            return
        if time.time() - _tried.get(chat_id, 0) < 300:
            return
        _tried[chat_id] = time.time()
        try:
            chat = await app.get_chat(chat_id)
            if not _is_forum(chat):
                logger.error(f"auto topics: {chat_id} me Topics ON nahi hain")
                return
            created, err = await setup_topics(chat_id)
            if err:
                logger.error(f"auto topics error: {err}")
        except Exception as e:
            logger.error(f"auto topics failed: {e}")


async def resolve_topic(cfg_chat, text):
    """
    batch.py yahi call karta hai.
    Return: (chat_id, topic_id). Agar user ne khud topic diya hai (-100xx/12) to wahi rahega.
    Agar chat me subject topics setup hain to subject se topic chuna jaayega.
    """
    chat_id, topic_id = _split_chat_topic(cfg_chat)
    if chat_id is None or topic_id is not None:
        return chat_id, topic_id
    try:
        doc = await _get_doc(chat_id)
        if not doc or not doc.get("subjects"):
            await _ensure_topics(chat_id)
            doc = await _get_doc(chat_id)
        if doc and doc.get("subjects"):
            subjects = doc["subjects"]
            for name, info in subjects.items():
                merged = list(info.get("kw", [])) + list(DEFAULT_SUBJECTS.get(name, []))
                info["kw"] = list(dict.fromkeys(merged))
            _, tid = _match_subject(text, subjects)
            return chat_id, tid
    except Exception as e:
        logger.error(f"resolve_topic error: {e}")
    return chat_id, None


async def setup_topics(chat_id):
    """Group me missing subject topics banata hai. Return (created, failed_reason)."""
    doc = await _get_doc(chat_id) or {"chat_id": int(chat_id), "subjects": {}}
    subjects = doc.get("subjects", {})
    created = []
    for name, kws in DEFAULT_SUBJECTS.items():
        if name in subjects:
            continue
        if name == GENERAL:
            # group ka built-in General topic use hoga (id None => seedha General me jaata hai)
            subjects[name] = {"id": None, "kw": []}
            continue
        try:
            t = await app.create_forum_topic(chat_id, name)
            subjects[name] = {"id": t.id, "kw": kws}
            created.append(name)
        except Exception as e:
            if created or subjects:
                await topics_col.update_one({"chat_id": int(chat_id)}, {"$set": {"subjects": subjects}}, upsert=True)
            return created, str(e)
    await topics_col.update_one({"chat_id": int(chat_id)}, {"$set": {"subjects": subjects}}, upsert=True)
    return created, None


# ── Bot ko admin banaya -> auto setup ──────────────────────────────────────────
@app.on_chat_member_updated()
async def on_bot_admin(client, upd):
    try:
        new = upd.new_chat_member
        if not new or not new.user or not new.user.is_self:
            return
        if new.status != enums.ChatMemberStatus.ADMINISTRATOR:
            return
        chat = upd.chat
        if not _is_forum(chat):
            await client.send_message(
                chat.id,
                "ℹ️ Is group me **Topics** chalu nahi hain.\n"
                "Group Settings → Topics ON karo, fir mujhe 'Manage Topics' right ke saath admin banao "
                "(ya /synctopics bhejo).\n\n"
                "⚠️ Topics ON karne par group ki ID badal sakti hai. Naya ID dekhne ke liye /chatid bhejo.",
            )
            return
        if not (new.privileges and new.privileges.can_manage_topics):
            await client.send_message(chat.id, "⚠️ Mujhe **Manage Topics** admin right do, fir /synctopics bhejo.")
            return
        created, err = await setup_topics(chat.id)
        msg = f"✅ Subject topics ready: {len(created)} naye topics bane."
        if err:
            msg = f"⚠️ Kuch topics nahi ban paaye: {err[:150]}"
        await client.send_message(chat.id, msg + f"\n\nAb apni /settings → SETCHATID me `{chat.id}` daalo — files subject ke hisaab se apne-aap sahi topic me jaayengi.")
    except Exception as e:
        logger.error(f"on_bot_admin error: {e}")


# ── Permission: bot owner YA us group ka admin ─────────────────────────────────
async def _allowed(client, message):
    try:
        # anonymous admin (group ke naam se bheja gaya message)
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if not message.from_user:
            return False
        uid = message.from_user.id
        if uid in OWNER_ID:
            return True
        m = await client.get_chat_member(message.chat.id, uid)
        if m.status in (enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR):
            return True
        await message.reply(f"⛔ Sirf owner/admin use kar sakta hai.\nTumhari ID: `{uid}`")
        return False
    except Exception as e:
        logger.error(f"_allowed error: {e}")
        return False


# ── Commands (owner / group admin) ─────────────────────────────────────────────
@app.on_message(filters.command("synctopics") & group_or_forum)
async def sync_cmd(client, message):
    if not await _allowed(client, message):
        return
    if not _is_forum(message.chat):
        await message.reply(f"Pehle group me Topics ON karo.\n🆔 Group ID: `{message.chat.id}`")
        return
    created, err = await setup_topics(message.chat.id)
    res = f"✅ {len(created)} topics bane." if not err else f"⚠️ Error: {err[:150]}\nCreated: {len(created)}"
    await message.reply(res + f"\n\n🆔 Group ID: `{message.chat.id}`\n/settings → SETCHATID me yahi ID daalo.")


@app.on_message(filters.command("chatid") & group_or_forum)
async def chatid_cmd(client, message):
    if not await _allowed(client, message):
        return
    await message.reply(
        f"🆔 Group ID: `{message.chat.id}`\n"
        f"Topics: {'ON ✅' if _is_forum(message.chat) else 'OFF ❌'}\n\n"
        "/settings → SETCHATID me yahi ID daalo."
    )


@app.on_message(filters.command("topics") & group_or_forum)
async def list_cmd(client, message):
    if not await _allowed(client, message):
        return
    doc = await _get_doc(message.chat.id)
    if not doc or not doc.get("subjects"):
        await message.reply("Topics setup nahi hain. /synctopics bhejo.")
        return
    lines = [f"• **{n}** — {', '.join(i.get('kw', [])[:4]) or 'default'}" for n, i in doc["subjects"].items()]
    await message.reply("📚 **Subject topics**\n\n" + "\n".join(lines) +
                        "\n\n`/addkw Subject keyword` se keyword jodo.")


@app.on_message(filters.command("addkw") & group_or_forum)
async def addkw_cmd(client, message):
    if not await _allowed(client, message):
        return
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.reply("Use: `/addkw Physics numericals`")
        return
    name, kw = parts[1], parts[2].strip().lower()
    doc = await _get_doc(message.chat.id)
    subj = (doc or {}).get("subjects", {})
    key = next((k for k in subj if k.lower() == name.lower()), None)
    if not key:
        await message.reply("Ye subject nahi mila. /topics dekho.")
        return
    if kw not in subj[key]["kw"]:
        subj[key]["kw"].append(kw)
    await topics_col.update_one({"chat_id": message.chat.id}, {"$set": {"subjects": subj}})
    await message.reply(f"✅ **{key}** me keyword jud gaya: `{kw}`")
