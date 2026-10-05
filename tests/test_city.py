"""The free city check after Gemini (normalize.doubtful_city): an event "in Bogotá" whose caption names only another
city gets the city doubt instead of going out as a Bogotá event. No network."""

from pa_bailar.normalize import CITY_DOUBT, doubtful_city, normalize_event
from tests.factories import extracted


def test_a_caption_naming_only_another_city_makes_the_city_doubtful():
    # La Revuelta Latin Fest, Oct 2026: read by Flash-Lite as a Bogotá event.
    event = doubtful_city(extracted(venue="Expofitness", address=None), "Nos vemos en expofitness Medellín 2027 🔥")
    assert event.in_bogota == "unknown"
    assert CITY_DOUBT in normalize_event(event).doubts


def test_bogota_named_an_address_or_no_other_city_keeps_it_in_bogota():
    assert doubtful_city(extracted(address=None), "Desde Cali para Bogotá: gran social").in_bogota == "yes"
    # A guest artist from elsewhere, at a venue with its own address (La Guillaera, Oct 2026).
    assert doubtful_city(extracted(address="Calle 22 #1-26"), "Llega desde Medellín La Guillaera").in_bogota == "yes"
    assert doubtful_city(extracted(address=None), "Social de salsa este sábado, con calidad").in_bogota == "yes"
    assert doubtful_city(extracted(address=None, in_bogota="no"), "Taller en Medellín").in_bogota == "no"
