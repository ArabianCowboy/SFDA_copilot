"""Browser coverage for the account page: the record, the standing line,
identity save, and the instant-apply preferences."""

from playwright.sync_api import Page, expect


def test_the_record_loads_from_the_mocked_profile(authenticated_page: Page):
    authenticated_page.goto("/account")

    expect(authenticated_page.locator("#account-record")).to_be_visible()
    expect(authenticated_page.locator("#account-monogram")).to_have_text("TU")
    expect(authenticated_page.locator("#account-heading")).to_have_text("Test User")
    expect(authenticated_page.locator("#account-email")).to_have_text("test@example.com")

    expect(authenticated_page.locator("#identity-first-name")).to_have_value("Test")
    expect(authenticated_page.locator("#identity-family-name")).to_have_value("User")
    expect(authenticated_page.locator("#identity-organization")).to_have_value("Test Organization")


def test_the_standing_line_reads_the_testing_bypass_identity(authenticated_page: Page):
    """fake_token resolves to role=user, tier=free (app.py's _TESTING_IDENTITIES).
    created_at/conversation_count are null under TESTING (no service-role
    key), which the standing line renders as an em dash rather than a
    fabricated number."""
    authenticated_page.goto("/account")

    expect(authenticated_page.locator("#standing-role")).to_have_text("Reader")
    expect(authenticated_page.locator("#standing-tier")).to_have_text("Free")
    expect(authenticated_page.locator("#standing-status")).to_have_text("Active")
    expect(authenticated_page.locator("#standing-since")).to_have_text("—")
    expect(authenticated_page.locator("#standing-conversations")).to_have_text("—")


def test_the_identity_save_button_starts_disabled_and_arms_on_edit(authenticated_page: Page):
    authenticated_page.goto("/account")

    expect(authenticated_page.locator("#identity-save")).to_be_disabled()
    authenticated_page.locator("#identity-first-name").fill("Changed")
    expect(authenticated_page.locator("#identity-save")).to_be_enabled()


def test_saving_identity_sends_the_writable_columns_and_shows_the_note(authenticated_page: Page):
    authenticated_page.goto("/account")

    authenticated_page.locator("#identity-first-name").fill("Updated")
    authenticated_page.locator("#identity-age").fill("30")
    authenticated_page.locator("#identity-form").evaluate("(form) => form.requestSubmit()")

    expect(authenticated_page.locator("#identity-saved-note")).to_be_visible()
    expect(authenticated_page.locator("#identity-save")).to_be_disabled()

    sent = authenticated_page.evaluate("window.__supabaseState.lastProfileUpdate")
    assert sent["first_name"] == "Updated"
    assert sent["age"] == 30
    assert "full_name" not in sent, (
        "full_name is a generated column and cannot be written since the identity cutover"
    )


def test_theme_choice_applies_instantly_and_persists(authenticated_page: Page):
    authenticated_page.goto("/account")

    authenticated_page.locator("#theme-choice-dark").check()
    expect(authenticated_page.locator("html")).to_have_attribute("data-bs-theme", "dark")
    expect(authenticated_page.locator("#preferences-saved-note")).to_be_visible()

    sent = authenticated_page.evaluate("window.__supabaseState.lastPreferencesPatch")
    assert sent == {"theme": "dark"}


def test_signed_out_visitor_sees_the_signed_out_state(browser_page: Page):
    browser_page.goto("/account")
    expect(browser_page.locator("#account-signed-out")).to_be_visible()
    expect(browser_page.locator("#account-record")).to_be_hidden()


def test_services_getprofile_and_updateprofile_contracts(authenticated_page: Page):
    """Not UI-specific — Services.getProfile/updateProfile called directly,
    independently of any page's markup. Moved here from the retired
    #profileModal's own test file; the contract it pins predates and outlives
    that surface."""
    result = authenticated_page.evaluate(
        """
        async () => {
          const { Services } = await import('/static/js/modules/services.js');
          const success = await Services.updateProfile(
            'test-user-id',
            { first_name: 'Contract Test' }
          );

          window.__supabaseState.profileUpdateError = 'Update failed';
          let updateError = null;
          try {
            await Services.updateProfile(
              'test-user-id',
              { first_name: 'Rejected Update' }
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
