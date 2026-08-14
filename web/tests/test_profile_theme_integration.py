"""Browser tests for profile editing and theme preference updates."""

from playwright.sync_api import Page, expect


def test_profile_form_loads_cached_profile(authenticated_page: Page):
    authenticated_page.locator("#profile-button").click()

    expect(authenticated_page.locator("#profileModal")).to_be_visible()
    expect(authenticated_page.locator("#profile-full-name")).to_have_value(
        "Test User"
    )
    expect(authenticated_page.locator("#profile-organization")).to_have_value(
        "Test Organization"
    )


def test_profile_update_applies_and_persists_theme(authenticated_page: Page):
    authenticated_page.locator("#profile-button").click()
    authenticated_page.locator("#profile-full-name").fill("Updated User")
    authenticated_page.locator("#theme-dark").check()
    authenticated_page.locator("#profile-form").evaluate(
        "(form) => form.requestSubmit()"
    )

    expect(authenticated_page.locator("html")).to_have_attribute(
        "data-bs-theme", "dark"
    )
    expect(authenticated_page.locator("#profileModal")).to_be_hidden()
    assert authenticated_page.evaluate(
        "window.__supabaseState.lastProfileUpdate.full_name"
    ) == "Updated User"
    assert authenticated_page.evaluate(
        "window.__supabaseState.lastProfileUpdate.preferences.theme"
    ) == "dark"


def test_profile_update_sends_only_the_columns_it_may_write(authenticated_page: Page):
    """The upsert payload is a privilege boundary, not just a shape.

    `authenticated` no longer holds table-wide INSERT/UPDATE on public.profiles.
    The write columns are granted one by one, precisely so that `role`, `tier`
    and `is_disabled` are excluded and a reader cannot promote themselves. The
    consequence is that naming *any* ungranted column fails the whole statement
    with "permission denied for table profiles" — Postgres reports a column
    miss as a table-level error, which makes it read like a much bigger problem
    than it is.

    That is not hypothetical: this form used to send `updated_at: new Date()`,
    which broke every profile save the moment the grants were narrowed. The
    trigger sets updated_at from the server clock anyway.

    The browser mock accepts anything, so only this assertion stands between a
    new field here and a 42501 in production.
    """
    granted = {"id", "full_name", "organization", "specialization", "preferences"}

    authenticated_page.locator("#profile-button").click()
    authenticated_page.locator("#profile-full-name").fill("Column Check")
    authenticated_page.locator("#profile-form").evaluate(
        "(form) => form.requestSubmit()"
    )

    sent = set(
        authenticated_page.evaluate(
            "Object.keys(window.__supabaseState.lastProfileUpdate)"
        )
    )
    assert sent <= granted, (
        f"profile upsert names column(s) the browser has no grant on: "
        f"{sorted(sent - granted)}. Either drop them from the payload, or add "
        f"them to the column grants in supabase/migrations/*_lock_profile_* "
        f"— but never add role, tier or is_disabled."
    )


def test_profile_service_contracts(authenticated_page: Page):
    result = authenticated_page.evaluate(
        """
        async () => {
          const { Services } = await import('/static/js/modules/services.js');
          const success = await Services.updateProfile(
            'test-user-id',
            { full_name: 'Contract Test' }
          );

          window.__supabaseState.profileUpdateError = 'Update failed';
          let updateError = null;
          try {
            await Services.updateProfile(
              'test-user-id',
              { full_name: 'Rejected Update' }
            );
          } catch (error) {
            updateError = error.message;
          }

          window.__supabaseState.profileError = { code: 'PGRST116' };
          const missingProfile = await Services.getProfile('missing-user');

          window.__supabaseState.profileError = {
            code: 'PGRST500',
            message: 'Profile lookup failed',
          };
          let profileError = null;
          try {
            await Services.getProfile('test-user-id');
          } catch (error) {
            profileError = error.message;
          }

          return { success, updateError, missingProfile, profileError };
        }
        """
    )

    assert result == {
        "success": True,
        "updateError": "Update failed",
        "missingProfile": None,
        "profileError": "Profile lookup failed",
    }
