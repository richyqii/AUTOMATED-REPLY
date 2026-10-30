import httpx

from app.manage import subscription


def setup_client(monkeypatch, settings, *, sender_number="+1 555 123 4567", subscribed=False):
    requests = []
    original_client = httpx.Client

    def handler(request):
        requests.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer unit-test-access-token-only"
        if request.url.path.endswith("/phone_numbers"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": settings.whatsapp_phone_number_id,
                            "display_phone_number": sender_number,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/subscribed_apps") and request.method == "GET":
            data = (
                [{"whatsapp_business_api_data": {"id": settings.meta_app_id}}] if subscribed else []
            )
            return httpx.Response(200, json={"data": data})
        if request.url.path.endswith("/subscribed_apps") and request.method == "POST":
            return httpx.Response(200, json={"success": True})
        raise AssertionError(f"Unexpected Meta request: {request.method} {request.url.path}")

    def factory(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("app.manage.httpx.Client", factory)
    return requests


def configured(settings):
    return settings.model_copy(
        update={
            "meta_app_id": "111222333444555",
            "whatsapp_business_account_id": "555444333222111",
        }
    )


def test_subscription_read_only(monkeypatch, settings):
    settings = configured(settings)
    requests = setup_client(monkeypatch, settings)
    assert "not subscribed" in subscription(settings, create=False)
    assert [method for method, _ in requests] == ["GET", "GET"]


def test_subscription_can_be_inspected_before_app_id_is_known(monkeypatch, settings):
    settings = configured(settings).model_copy(update={"meta_app_id": ""})
    requests = setup_client(monkeypatch, settings)
    assert "Set META_APP_ID" in subscription(settings, create=False)
    assert [method for method, _ in requests] == ["GET", "GET"]


def test_subscribe_only_checked_test_waba(monkeypatch, settings):
    settings = configured(settings)
    requests = setup_client(monkeypatch, settings)
    assert "Subscribed" in subscription(settings, create=True)
    assert [method for method, _ in requests] == ["GET", "GET", "POST"]


def test_mismatch_never_subscribes(monkeypatch, settings):
    settings = configured(settings)
    requests = setup_client(monkeypatch, settings, sender_number="+60 12-418 2788")
    assert "does not match" in subscription(settings, create=True)
    assert [method for method, _ in requests] == ["GET"]


def test_production_mode_never_auto_subscribes(monkeypatch, settings):
    settings = configured(settings).model_copy(update={"whatsapp_sender_mode": "production"})
    requests = setup_client(monkeypatch, settings)
    assert "restricted to test mode" in subscription(settings, create=True)
    assert [method for method, _ in requests] == ["GET", "GET"]
