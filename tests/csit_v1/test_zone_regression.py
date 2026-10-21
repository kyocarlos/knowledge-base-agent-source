import pytest

@pytest.mark.parametrize("zone",["test","da40","rd2"])
def test_existing_zone_grant_selection(zone):
    from test_passwordless_binding import BindingTests
    fixture=BindingTests(methodName="test_existing_grant_selection_logout_regression")
    fixture.setUp()
    try:
        fixture.r.grant(fixture.admin.user_id,fixture.normal.user_id,zone,"user")
        fixture.admin_cookie(fixture.r.get_user(fixture.normal.user_id))
        r=fixture.client.post("/api/auth/select-instance",json={"instance_id":zone})
        assert r.status_code==200
        assert fixture.client.get("/api/auth/me").json()["instances"]==[{"instance_id":zone,"role":"user"}]
    finally:fixture.tearDown()
