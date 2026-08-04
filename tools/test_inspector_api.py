import os, sys, time, json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import app as flask_app

def test_api():
    client = flask_app.app.test_client()

    print("Testing GET /video-inspector...")
    res = client.get("/video-inspector")
    assert res.status_code == 200
    assert b"Video Library Inspector" in res.data
    print("GET /video-inspector: OK (200)")

    print("Testing GET /api/video-inspector/status...")
    res = client.get("/api/video-inspector/status")
    assert res.status_code == 200
    status_data = res.get_json()
    print("Inspector Status:", status_data)

    print("Testing POST /api/video-inspector/reset...")
    res = client.post("/api/video-inspector/reset")
    assert res.status_code == 200

    print("All Inspector API tests passed!")

if __name__ == "__main__":
    test_api()
