"""The pre-filter (prefilter.py): what it never skips (anything an announcement says, in the caption or the image), what
it does (a caption and an image that say nothing of an event), and how the sweep runs it in each mode (shadow: recorded
next to Gemini's verdict, nothing skipped; on; off)."""

from datetime import datetime

import pytest

from pa_bailar import config, health, prefilter, status, storage
from pa_bailar.commands.sweep import summary_markdown
from pa_bailar.models import PostAnalysis
from tests.factories import make_image
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post, run

PHOTO = make_image()


def no_text(image: bytes) -> str:
    return ""  # OCR found no text: a photo of dancers


# Announcements as Colombian academies, bars and organizers write them: none may ever be skipped, whatever the image.
EVENT_CAPTIONS = [
    "Social de salsa este sábado 💃",
    "SOCIAL DE SALSA ESTE SABADO",
    "𝐒𝐎𝐂𝐈𝐀𝐋 𝐃𝐄 𝐁𝐀𝐂𝐇𝐀𝐓𝐀",  # Instagram's fancy font
    "Sáb 18 · nos vemos",
    "sab 18",
    "Vie 17 Oct",
    "Hoy!!! 🔥",
    "hoy se baila",
    "Mañana a las 20:00",
    "Manana 8pm",
    "este finde 🔥🔥",
    "Este fin de semana se goza",
    "Cover $30k",
    "Valor 30.000",
    "20 mil la entrada",
    "Entrada libre",
    "gratis",
    "8pm",
    "a las 9 p.m.",
    "20:00",
    "18 de octubre",
    "18/10",
    "del 13 al 16 de noviembre",
    "Nos vemos el 18",
    "Taller de bachata sensual",
    "Workshop con Juan y Ana",
    "Clase abierta de casino",
    "Bootcamp intensivo",
    "Noche de salsa brava",
    "Rumba en la terraza",
    "Fiesta neón",
    "Concierto de La 33",
    "Congreso Internacional de Salsa",
    "Festival de bachata",
    "Milonga de los jueves",
    "Práctica abierta",
    "Te esperamos 💃",
    "Los esperamos con toda",
    "No te lo pierdas",
    "Cupos limitados, inscríbete ya",
    "Reserva tu mesa",
    "📍 Calle 85 #12-34",
    "Cra 7 No. 45",
    "Info al 300 123 4567",
    "Link en la bio",
    "Escríbenos al DM",
    "Boletería en taquilla",
    "Preventa disponible",
    "#socialdesalsa #bogota",
    "#sabadodebachata",
    "Save the date ✨",
    "Tonight we dance",
    "Free entry",
    "Line up oficial 2026",
    "Aniversario 10 años",
    "Orquesta en vivo",
    "🗓️ 🕘",
    "Vente pues",
    "Halloween party 🎃",
]


@pytest.mark.parametrize("caption", EVENT_CAPTIONS)
def test_an_announcements_caption_is_never_skipped(caption):
    verdict = prefilter.judge(caption, [PHOTO], read_text=no_text)
    assert not verdict.skip and not verdict.text_silent, verdict.reason


# Posts that obviously announce nothing: skipped once their image is shown to carry no text.
NOT_EVENT_CAPTIONS = [
    "Gracias a todos por tanto cariño 🙏❤️",
    "Aprende este giro paso a paso 👇 Guarda este video para repasarlo",
    "Cuando escuchas la primera nota de tu canción favorita 😂",
    "Sorteo de una camiseta: comenta y etiqueta a tus amigos 🎁",
    "Feliz cumple a nuestra profe más linda 🎂",
    "🔥🔥🔥",
    "",
    None,
]


@pytest.mark.parametrize("caption", NOT_EVENT_CAPTIONS)
def test_a_post_that_says_nothing_of_an_event_in_text_or_image_is_skipped(caption):
    verdict = prefilter.judge(caption, [PHOTO], read_text=no_text)
    assert verdict.skip and verdict.text_silent


def test_a_flyer_with_a_silent_caption_is_read():
    """A flyer may carry everything: "¡Los esperamos!" is a signal, but even "🔥" with a flyer is read."""
    flyer = "SOCIAL DE SALSA\nSÁBADO 18 OCT | 8 PM\nCOVER 20K"
    verdict = prefilter.judge("🔥", [PHOTO], read_text=lambda image: flyer)
    assert not verdict.skip and verdict.text_silent and "imagen 1" in verdict.reason


def test_an_image_with_more_than_a_few_letters_is_read_even_without_event_words():
    """A flyer whose date OCR misreads (stylized digits) still has text: more than a few letters is enough."""
    words = "La vida es mejor cuando bailas con el corazón"
    assert not prefilter.judge("🔥", [PHOTO], read_text=lambda image: words).skip
    assert prefilter.judge("🔥", [PHOTO], read_text=lambda image: "@academia").skip  # a watermark


def test_an_image_with_digits_is_read():
    """A handwritten flyer OCR only half read ("Previa | 19 … ESPACIO 64", 9 Oct 2026), a countdown's "24"."""
    assert not prefilter.judge("🔥", [PHOTO], read_text=lambda image: "Previa | 19\nESPACIO\n64").skip
    assert not prefilter.judge("", [PHOTO], read_text=lambda image: "24").skip


def test_every_image_is_checked_not_only_the_first():
    texts = iter(["", "TALLER DE SALSA"])
    verdict = prefilter.judge("Gracias", [PHOTO, PHOTO], read_text=lambda image: next(texts))
    assert not verdict.skip and "imagen 2" in verdict.reason


def test_without_ocr_an_image_and_a_short_caption_are_read():
    """The sweep has no OCR (not in requirements.txt): an image it can't read may be a flyer, so nothing is skipped."""
    verdict = prefilter.judge("🔥", [PHOTO])  # tests: no OCR (conftest)
    assert not verdict.skip and verdict.text_silent and "sin OCR" in verdict.reason


def test_a_long_carousel_is_read():
    images = [PHOTO] * (config.PREFILTER_MAX_IMAGES + 1)
    assert not prefilter.judge("Gracias", images, read_text=no_text).skip


# ---------- in the sweep ----------


@pytest.fixture(autouse=True)
def accounts_and_images(isolated_files, monkeypatch):
    config.ACCOUNTS_FILE.write_text("academia\n", encoding="utf-8")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


def with_caption(post_id: str, caption: str) -> dict:
    return {**post(post_id), "caption": caption}


def sweep(posts, extractor, monkeypatch, mode="shadow", image_text=no_text):
    monkeypatch.setattr(config, "PREFILTER_MODE", mode)
    monkeypatch.setattr(prefilter, "image_text", image_text)
    return run(FakeInstagram({"academia": posts}), extractor)


def test_in_shadow_a_post_it_would_skip_still_goes_to_the_triage_and_both_verdicts_are_recorded(monkeypatch):
    extractor = FakeExtractor({}, not_events={"thanks"})
    stats = sweep([with_caption("thanks", "Gracias 🙏")], extractor, monkeypatch)
    assert "thanks" in extractor.rules_seen  # the triage read it: nothing is skipped in shadow
    record = storage.load_processed_posts()["thanks"]
    assert record.prefilter is not None
    assert (record.prefilter.verdict, record.prefilter.gemini_event) == ("skip", False)
    assert stats.prefilter == {"judged": 1, "would_skip": 1, "text_silent": 1}
    assert stats.prefilter_disagreements == []


def test_in_shadow_a_post_it_would_skip_that_gemini_calls_an_event_is_a_disagreement(monkeypatch):
    extractor = FakeExtractor({"flyer": event_post("flyer")})
    stats = sweep([with_caption("flyer", "🔥")], extractor, monkeypatch)
    assert extractor.extracted_posts == ["flyer"]  # still read and published
    assert stats.events_new == 1
    assert stats.prefilter["disagreements"] == 1 and stats.prefilter["text_silent_events"] == 1
    assert stats.prefilter_disagreements == ["https://www.instagram.com/p/flyer/"]
    assert health.record_of(stats, []).prefilter_disagreements == stats.prefilter_disagreements  # run_history.json
    assert "⚠️ would skip https://www.instagram.com/p/flyer/" in summary_markdown(stats)


def test_without_ocr_a_silent_caption_is_read_and_counted_as_shadow_data(monkeypatch):
    """The sweep's case today: no OCR, so it would skip nothing; what it records still shows how often an event is
    all in the image (a silent caption Gemini calls an event)."""
    extractor = FakeExtractor({"flyer": event_post("flyer")})
    stats = sweep([with_caption("flyer", "🔥")], extractor, monkeypatch, image_text=lambda image: None)
    record = storage.load_processed_posts()["flyer"]
    assert record.prefilter is not None and record.prefilter.verdict == "read"
    assert stats.prefilter == {"judged": 1, "text_silent": 1, "text_silent_events": 1}


def test_an_announcement_is_read_and_recorded_with_its_reason(monkeypatch):
    extractor = FakeExtractor({"social": event_post("social")})
    stats = sweep([with_caption("social", "Social este sábado 8pm")], extractor, monkeypatch)
    record = storage.load_processed_posts()["social"]
    assert record.prefilter is not None
    assert record.prefilter.verdict == "read" and "social" in record.prefilter.reason
    assert record.prefilter.gemini_event is True
    assert stats.prefilter == {"judged": 1}


def test_on_skips_the_triage_for_posts_it_would_skip_and_reads_the_rest(monkeypatch):
    extractor = FakeExtractor({"social": event_post("social")})
    posts = [with_caption("thanks", "Gracias 🙏"), with_caption("social", "Social este sábado")]
    stats = sweep(posts, extractor, monkeypatch, mode="on")
    assert "thanks" not in extractor.rules_seen and extractor.extracted_posts == ["social"]
    record = storage.load_processed_posts()["thanks"]
    assert record.outcome == "not_event" and record.model == "prefilter"
    assert record.reason.startswith("pre-filtro: ")
    assert record.prefilter is not None and record.prefilter.gemini_event is None
    assert stats.prefilter == {"judged": 2, "skipped": 1, "text_silent": 1}
    assert stats.posts_triaged_out == 1


def test_off_judges_nothing(monkeypatch):
    extractor = FakeExtractor({}, not_events={"thanks"})
    stats = sweep([with_caption("thanks", "Gracias 🙏")], extractor, monkeypatch, mode="off")
    assert storage.load_processed_posts()["thanks"].prefilter is None
    assert stats.prefilter == {} and "Pre-filter" not in summary_markdown(stats)


def test_a_post_that_had_events_and_is_edited_skips_the_pre_filter_as_it_skips_the_triage(monkeypatch):
    """A post that had events is read again by the extraction whatever its caption says now ("CANCELADO")."""
    first = FakeExtractor({"social": event_post("social")})
    sweep([with_caption("social", "Social este sábado")], first, monkeypatch, mode="on")
    cancelled = PostAnalysis(is_event_post=False, reason="cancelado", events=[])
    again = FakeExtractor({"social": cancelled})
    sweep([with_caption("social", "🙏")], again, monkeypatch, mode="on")
    assert again.extracted_posts == ["social"]
    assert storage.load_processed_posts()["social"].prefilter is None


# ---------- the status (admin status, PB Admin) ----------


def test_the_status_sums_the_shadow_data_and_marks_disagreements():
    runs = [
        {"finished_at": "2026-10-09T21:12:00-05:00", "prefilter": {"judged": 20, "would_skip": 2, "text_silent": 3}},
        {
            "finished_at": "2026-10-10T06:42:00-05:00",
            "prefilter": {"judged": 10, "would_skip": 1, "text_silent": 2, "text_silent_events": 1, "disagreements": 1},
            "prefilter_disagreements": ["https://www.instagram.com/p/x/"],
        },
        {"finished_at": "2026-10-10T09:00:00-05:00"},  # before it existed
    ]
    found = status.collect(
        now=datetime.fromisoformat("2026-10-10T12:00:00-05:00"),
        instagram=None,
        read=lambda name, default: runs if name == "run_history.json" else default,
    )["prefilter"]
    assert found["judged"] == 30 and found["would_skip"] == 3 and found["disagreements"] == 1 and found["runs"] == 2
    assert found["disagreement_posts"] == ["https://www.instagram.com/p/x/"]
    line = status.prefilter_line(found, datetime.fromisoformat("2026-10-10T12:00:00-05:00"))
    assert line.startswith(
        "⚠️ Pre-filtro (en sombra, desde ayer 9:12 p. m., 2 barridos): de 30 publicaciones saltaría 3"
    )
    assert "https://www.instagram.com/p/x/" in line and "Gemini vio evento en 1 (estaba en la imagen)" in line
