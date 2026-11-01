# iamtghelp - Auto subject-wise topics
# Bot ko forum group me admin banao -> subject topics apne-aap ban jaate hain.
# Files/posts ke naam + caption se subject pehchan kar sahi topic me bheji jaati hain.

import re
import logging
from pyrogram import filters, enums
from shared_client import app
from config import OWNER_ID
from utils.func import db

logger = logging.getLogger("iamtghelp")
topics_col = db["subject_topics"]

GENERAL = "General"
WEAK = {"Science"}

# Topic naam -> keywords (English + Hindi). Lowercase me match hota hai.
DEFAULT_SUBJECTS = {
    "Physics": ["physics", "phy ", "भौतिक", "फिजिक्स"],
    "Chemistry": ["chemistry", "chem ", "रसायन", "केमिस्ट्री"],
    "Maths": ["maths", "math ", "mathematics", "गणित", "algebra", "geometry", "trigonometry", "calculus"],
    "Biology": ["biology", "bio ", "जीव विज्ञान", "बायोलॉजी", "botany", "zoology"],
    "Hindi": ["hindi", "हिंदी", "हिन्दी", "vyakaran", "व्याकरण"],
    "English": ["english", "grammar", "अंग्रेजी", "अंग्रेज़ी"],
    "Sanskrit": ["sanskrit", "संस्कृत"],
    "History": ["history", "इतिहास"],
    "Geography": ["geography", "भूगोल"],
    "Polity": ["polity", "civics", "constitution", "राजनीति", "नागरिक शास्त्र"],
    "Economics": ["economics", "economy", "अर्थशास्त्र"],
    "Science": ["general science", "science", "विज्ञान"],
    "GK-GS": ["gk", "gs", "general knowledge", "general studies", "current affairs", "सामान्य ज्ञान", "करेंट अफेयर्स"],
    "Reasoning": ["reasoning", "रीजनिंग", "तर्कशक्ति", "mental ability"],
    "Computer": ["computer", "कंप्यूटर"],
    GENERAL: [],
}


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
                kw_n = kw.lower()
                if kw_n and kw_n in t and len(kw_n) > best_len:
                    best, best_len = name, len(kw_n)
        if best:
            break
    if best:
        return best, subjects[best]["id"]
    g = subjects.get(GENERAL)
    return (GENERAL, g["id"]) if g else (None, None)


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
        if doc and doc.get("subjects"):
            _, tid = _match_subject(text, doc["subjects"])
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
        if not getattr(chat, "is_forum", False):
            await client.send_message(
                chat.id,
                "ℹ️ Is group me **Topics** chalu nahi hain.\n"
                "Group Settings → Topics ON karo, fir mujhe 'Manage Topics' right ke saath admin banao "
                "(ya /synctopics bhejo).",
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


# ── Commands (owner only) ──────────────────────────────────────────────────────
@app.on_message(filters.command("synctopics") & filters.group)
async def sync_cmd(client, message):
    if not message.from_user or message.from_user.id not in OWNER_ID:
        return
    if not getattr(message.chat, "is_forum", False):
        await message.reply("Pehle group me Topics ON karo.")
        return
    created, err = await setup_topics(message.chat.id)
    await message.reply(
        f"✅ {len(created)} topics bane." if not err else f"⚠️ Error: {err[:150]}\nCreated: {len(created)}"
    )


@app.on_message(filters.command("topics") & filters.group)
async def list_cmd(client, message):
    if not message.from_user or message.from_user.id not in OWNER_ID:
        return
    doc = await _get_doc(message.chat.id)
    if not doc or not doc.get("subjects"):
        await message.reply("Topics setup nahi hain. /synctopics bhejo.")
        return
    lines = [f"• **{n}** — {', '.join(i.get('kw', [])[:4]) or 'default'}" for n, i in doc["subjects"].items()]
    await message.reply("📚 **Subject topics**\n\n" + "\n".join(lines) +
                        "\n\n`/addkw Subject keyword` se keyword jodo.")


@app.on_message(filters.command("addkw") & filters.group)
async def addkw_cmd(client, message):
    if not message.from_user or message.from_user.id not in OWNER_ID:
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
