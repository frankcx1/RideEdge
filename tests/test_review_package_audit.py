from scripts.audit_review_package import findings, private_values


def test_known_private_values_and_credentials_detected_without_echo():
    private = "synthetic-secret-for-audit"
    assert findings(private.encode(), {private}) == {"known private value"}
    marker = b"-----BEGIN " + b"PRIVATE KEY-----"
    assert findings(marker, set()) == {"private key"}
    assert findings(("sk-" + "x" * 30).encode(), set()) == {"credential pattern"}


def test_coordinates_match_exact_numbers_not_neighboring_public_values():
    known = {"47.611", "-122.331"}
    assert findings(b'"latitude": 47.611, "longitude": -122.331', known)
    assert findings(b"routes_47.611_-122.331.json", known)
    assert not findings(b'"latitude": 47.611234, "longitude": -122.331234', known)


def test_private_origin_and_env_are_inputs_only(tmp_path):
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/zones.json").write_text(
        '{"origin":{"lat":47.611234,"lon":-122.331234,"label":"public_neighborhood"}}')
    (tmp_path / ".env").write_text("SOME_API_KEY=synthetic-secret-for-audit\nOTHER_SETTING=not-sensitive\n")
    known = private_values(tmp_path)
    assert "47.611234" in known and "-122.331" in known
    assert "synthetic-secret-for-audit" in known
    assert "not-sensitive" not in known and "public_neighborhood" not in known
