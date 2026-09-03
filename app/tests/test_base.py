def test_venture_analytics_requires_auth(client):
    response = client.get(
        "/api/v1/analytics/venture/11111111-1111-1111-1111-111111111111"
    )

    assert response.status_code in [401, 403]
