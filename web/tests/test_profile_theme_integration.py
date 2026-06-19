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
