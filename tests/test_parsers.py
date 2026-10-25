from allbal.ingest.boitesalivres_com import parse_boitesalivres_data
from allbal.ingest.lebouquinfrancais import parse_bal_js
from allbal.ingest.nonmarchand import parse_nonmarchand_html
from allbal.ingest.osm_overpass import parse_boites_gpx
from allbal.ingest.zonelivre import parse_zonelivre_markers


def test_parse_boites_gpx():
    gpx = """<?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
      <wpt lat="48.70718" lon="-0.58291">
        <name>Boite - 1</name>
        <desc>18 Rue Principale 61100 La Chapelle-au-Moine</desc>
      </wpt>
      <wpt lat="48.00566" lon="-1.84936">
        <name>Boite - 2</name>
        <desc>1 Rue du Perray 35580 Goven</desc>
      </wpt>
    </gpx>
    """
    images_map = {"1": True, "2": False}
    records = parse_boites_gpx(gpx, images_map=images_map)
    assert len(records) == 2
    r1 = records[0]
    assert r1["source_id"] == "1"
    assert r1["address"] == "18 Rue Principale"
    assert r1["postcode"] == "61100"
    assert r1["city"] == "La Chapelle-au-Moine"
    assert r1["photo_url"] == "https://www.boites-a-livres.fr/s/1"

    r2 = records[1]
    assert r2["photo_url"] is None


def test_parse_bal_js():
    js = """
    var villes = {
      "5": {"lat": 44.0415, "lon": 4.0982, "id": 5, "city": "Ribaute les tavernes"},
      "7": {"lat": 48.8755, "lon": 2.1790, "id": 7, "city": "Rueil malmaison"}
    };
    """
    records = parse_bal_js(js)
    assert len(records) == 2
    assert records[0]["source_id"] == "5"
    assert records[0]["city"] == "Ribaute les tavernes"
    assert records[1]["lat"] == 48.8755


def test_parse_nonmarchand_html():
    html = """
    <html>
      <dl class='map'>
        <dt> 0.3,-3.4 </dt><dd> Aide </dd>
        <dt> 45.89824/-0.95395 </dt><dd> <a href='https://nonmarchand.org/pmwiki/EspacesDeGratuite/20130916691'>Le café des amis</a> </dd>
        <dt> 46.15514,-1.15215 </dt><dd> <a href='https://nonmarchand.org/pmwiki/EspacesDeGratuite/20130918902'>Boîte à lire des graffs</a> </dd>
      </dl>
    </html>
    """
    records = parse_nonmarchand_html(html)
    assert len(records) == 2
    assert records[0]["title"] == "Le café des amis"
    assert records[0]["source_id"] == "20130916691"
    assert records[1]["lat"] == 46.15514


def test_parse_zonelivre_markers():
    data = {
        "total": 2,
        "items": [
            {"m": "17", "lt": "48.3893", "ln": "-4.5018", "t": "Brest", "i": 39},
            {"m": "18", "lt": "48.0932", "ln": "-4.3307", "t": "Douarnenez", "i": 39},
        ],
    }
    records = parse_zonelivre_markers(data)
    assert len(records) == 2
    assert records[0]["source_id"] == "17"
    assert records[0]["city"] == "Brest"
    assert records[0]["is_enriched"] == 0


def test_parse_boitesalivres_data():
    items = [
        {
            "id": 2,
            "adresse": "3 Rue du Faubourg Saint-Antoine",
            "cp": "75011",
            "ville": "Paris",
            "description": "Petite cabane bleue",
            "latitude": 48.8534,
            "longitude": 2.3741,
            "photo_url": "https://example.com/photo.jpg",
            "etat": "pleine",
        }
    ]
    records = parse_boitesalivres_data(items)
    assert len(records) == 1
    assert records[0]["source_id"] == "2"
    assert records[0]["address"] == "3 Rue du Faubourg Saint-Antoine"
    assert records[0]["status"] == "pleine"
    assert records[0]["photo_url"] == "https://example.com/photo.jpg"
