"""The admin tools' answers to `sweep --post`, `--story`, `--hide-story` and `--hide-event`, in Spanish markdown: the
workflow comments them on the admin issue (docs/ADMIN.md)."""

from urllib.parse import quote

from pa_bailar import config, links
from pa_bailar.models import StoredEvent
from pa_bailar.pipeline import AddedPost, AddedStory, HiddenFromSite, HiddenStory
from pa_bailar.status import moment_label
from pa_bailar.text import clock, day_label, event_dates_label, parse_hhmm

# ---------- a post ----------


def _event_line(event: StoredEvent) -> str:
    return f"- [{event.title}]({links.event_url(event.id)}) · {_dates(event)}"


def _dates(event: StoredEvent) -> str:
    """ "2026-11-13", "13–15 nov 2026", or a workshop series' sessions: "4 sesiones: 8, 22, 29 nov y 6 dic"."""
    return event_dates_label(event.date, event.end_date, event.session_dates)


def added_post_markdown(added: AddedPost) -> str:
    """The admin tools' answer after adding a post by hand, in Spanish."""
    lines: list[str] = []
    if added.public:
        lines.append(
            "📄 La leí desde su página pública: la API de Instagram no la entrega (cuenta personal, colaboración "
            "o límite)."
        )
    if not added.readable:
        lines.append(
            f"ℹ️ La API no puede leer @{added.account} (cuenta personal o privada): no entra en los barridos. "
            "Sus próximos eventos se agregan así, con el enlace."
        )
    if added.account_added:
        lines.append(
            f"➕ @{added.account} no estaba en los barridos: la agregué (sus publicaciones de los últimos "
            f"{config.BACKFILL_DAYS} días se leen en el próximo barrido)."
        )
    # Provisional reads are upgraded to Flash by the sweeps, which only see accounts the API can read.
    upgrade = "provisional: se relee con Flash" if added.readable and not added.public else "Flash no tenía cuota"
    light = f" Flash-Lite ({upgrade})" if added.provisional else f" {added.model}"
    if added.unchanged:
        lines.append(
            "ℹ️ Ya la había leído y no ha cambiado: no la leí de nuevo (no gasté cuota de Gemini). Para leerla "
            "otra vez (por ejemplo, si quedó con datos equivocados): **Volver a leer**."
        )
    if added.unchanged and added.outcome in ("event", "merged"):
        if added.events:
            lines.append(f"✅ **Ya está en el sitio** ({len(added.events)} evento(s)):")
            lines += [_event_line(e) for e in added.events]
        else:
            lines.append("✅ Su evento ya pasó: sale del sitio después de su fecha.")
    elif added.outcome in ("event", "merged") and added.events:
        verb = "Se unió a" if added.outcome == "merged" else "Publiqué"
        lines.append(f"✅ **{verb} {len(added.events)} evento(s)**, leído con{light}:")
        lines += [_event_line(e) for e in added.events]
        lines.append("")
        lines.append("Aparece en el sitio cuando termina de publicarse (unos minutos).")
    elif added.outcome == "discarded":
        why = f" ({added.detail})" if added.detail else ""
        lines.append(f"❌ Gemini la leyó como evento, pero no es publicable{why}: {added.reason}")
    else:
        lines.append(f"❌ Gemini dice que no anuncia un evento: “{added.reason}”")
    return "\n".join(lines) + "\n"


# ---------- a story (stories.py): the receipt, and hiding it; hiding an event ----------


def _day(event: StoredEvent) -> str:
    """ "sábado 10 oct 2026", or the range of an event over several days, or a workshop series' sessions."""
    return _dates(event) if event.end_date or not event.date else day_label(event.date)


def _story_event_line(event: StoredEvent) -> str:
    parts = [_day(event)]
    if event.start_time:
        parts.append(clock(parse_hhmm(event.start_time)))
    if event.venue:
        parts.append(event.venue)
    return f"- [{event.title}]({links.event_url(event.id)}) · {' · '.join(parts)}"


def _story_receipt(added: AddedStory) -> list[str]:
    """What was read from a story just published, and where each part came from (inferred parts flagged)."""
    checked = "" if added.account_checked else " ⚠️"
    lines = ["", "**Lo que leí:**", f"- Cuenta: @{added.account} ({added.account_source}){checked}"]
    for event in added.events:
        notes = added.date_notes.get(event.title)
        if notes:
            lines.append(f"- Fecha de “{event.title}”: {_day(event)} ({'; '.join(notes)})")
    if added.location:
        lines.append(f"- Lugar: {added.location} (del sticker de ubicación)")
    if added.mentions:
        mentions = ", ".join(f"@{name}" for name in added.mentions)
        lines.append(f"- Menciones: {mentions} (no son la cuenta del evento)")
    lines.append(f"- Captura: {moment_label(added.taken.isoformat(), config.now_bogota())} ({added.taken_source})")
    if not added.gemini_crop:
        lines.append("- Recorte: fijo (Gemini no marcó bien el flyer): revisa que se vea completo")
    if added.past:
        lines.append(f"- No publiqué, porque ya pasaron: {', '.join(added.past)}")
    return lines


def _story_published_footer(added: AddedStory, again: bool) -> list[str]:
    """After a published story's answer: its flyer's crop, when it shows on the site, and how to undo it."""
    flyers = [
        media.flyer
        for event in added.events
        for media in event.media
        if media.post_id == added.story_id and media.flyer
    ]
    lines = ["", f"![Recorte publicado]({config.SITE_URL}/{flyers[0]})"] if flyers else []
    if not again:
        lines += ["", "Aparece en el sitio cuando termina de publicarse (unos minutos)."]
    lines.append(
        f"¿Algo está mal? Ocultar: `/ocultar {added.story_id}` (o el botón en la página). Después puedes "
        "compartirla otra vez con la @cuenta o una nota."
    )
    return lines


def added_story_markdown(added: AddedStory) -> str:
    """The answer to "Agregar historia": what was published and a receipt of what was read and where each part
    came from (inferred parts flagged), the flyer's crop, and how to undo it (/ocultar)."""
    lines: list[str] = []
    again = added.unchanged or added.duplicate_of
    if added.unchanged:
        lines.append("ℹ️ Ya había publicado estas mismas capturas: no las leí de nuevo (no gasté cuota de Gemini).")
    if added.duplicate_of:
        lines.append(
            f"ℹ️ Es otra captura de una historia que ya publiqué (`{added.duplicate_of}`): no la leí de nuevo. Si es "
            "una historia distinta, compártela otra vez con una nota (Notas) y la leo."
        )
    published = added.outcome in ("event", "merged") and added.events
    if published and again:
        lines.append(f"✅ **Ya está en el sitio** ({len(added.events)} evento(s)):")
        lines += [_story_event_line(event) for event in added.events]
    elif published:
        verb = "Se unió a" if added.outcome == "merged" else "Publiqué"
        light = " Flash-Lite (Flash no tenía cuota)" if added.provisional else f" {added.model}"
        lines.append(f"✅ **{verb} {len(added.events)} evento(s)** desde la historia, leída con{light}:")
        lines += [_story_event_line(event) for event in added.events]
        lines += _story_receipt(added)
    elif added.past:
        lines.append(f"❌ Su fecha ya pasó: {', '.join(added.past)}. No publiqué nada.")
    elif added.outcome == "discarded":
        lines.append(f"❌ Gemini la leyó como evento, pero no es publicable (recurrente o sin fecha): {added.reason}")
    else:
        lines.append(f"❌ Gemini dice que no anuncia un evento: “{added.reason}”")
    if added.account_added:
        lines.append(
            f"➕ @{added.account} no estaba en los barridos: la agregué (sus publicaciones de los últimos "
            f"{config.BACKFILL_DAYS} días se leen en el próximo barrido)."
        )
    if published:
        lines += _story_published_footer(added, again=bool(again))
    else:
        lines.append(
            "Para intentarlo de nuevo, comparte las capturas otra vez (con la @cuenta o una nota si ayuda): las que "
            "subiste siguen guardadas hasta 7 días."
        )
    return "\n".join(lines) + "\n"


def hidden_story_markdown(hidden: HiddenStory) -> str:
    if hidden.already:
        return f"ℹ️ La historia `{hidden.story_id}` ya estaba oculta.\n"
    lines = [f"🙈 Oculté la historia `{hidden.story_id}` (@{hidden.account})."]
    lines += [f"- Quité del sitio: {event.title} · {_day(event)}" for event in hidden.removed]
    lines += [
        f"- Sigue en el sitio, porque otras publicaciones lo anuncian: [{event.title}]({links.event_url(event.id)})"
        for event in hidden.kept
    ]
    if not hidden.removed and not hidden.kept:
        lines.append("No tenía eventos en el sitio.")
    else:
        lines.append("")
        lines.append("Sale del sitio cuando termina de publicarse (unos minutos).")
    lines.append("Para publicarla de nuevo, comparte las capturas otra vez.")
    return "\n".join(lines) + "\n"


def hidden_event_markdown(hidden: HiddenFromSite) -> str:
    """The answer to "Ocultar" (an event, `sweep --hide-event`), in Spanish."""
    event = hidden.event
    if hidden.already:
        return f"ℹ️ El evento `{event.id}` ({event.title}) ya estaba oculto.\n\n" + _undo_hide(event)
    lines = [
        f"🙈 Quité del sitio **{event.title}** (@{event.account}) · {_dates(event)}.",
        "",
        "Sale del sitio cuando termina de publicarse (unos minutos). Los barridos no lo vuelven a publicar desde "
        "sus publicaciones ni desde otra publicación del mismo evento; un evento nuevo sí se publica.",
    ]
    return "\n".join(lines) + "\n\n" + _undo_hide(event)


def _undo_hide(event: StoredEvent) -> str:
    """How to publish a hidden event again, one line per post or story it came from: a post's link opens the
    admin page with it filled in (its share-target address, `?url=`), where Agregar publishes it again
    (Sweep.add_post reads it again: `_announced_hidden`)."""
    lines = ["**¿Fue por error?** Vuelve a publicarlo desde cualquiera de estas:"]
    stories = False
    for media in event.media:
        if media.media_type == "STORY":
            stories = True
            continue
        again = f"{config.ADMIN_URL}/?url={quote(media.permalink, safe='')}"
        lines.append(f"- [Publicación]({media.permalink}) · [Volver a publicarla]({again}) (toca **Agregar**)")
    if stories:
        lines.append(
            f"- Una historia de @{event.account}: comparte otra vez sus capturas con PB Admin "
            "(**Agregar desde una historia**)."
        )
    return "\n".join(lines) + "\n"
