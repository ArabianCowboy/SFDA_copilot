---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-19
supersedes_note: >
  An AI first-pass QA over copy a human had already signed off. Its one
  "must fix" was applied the same day (e9f3e2a) after two independent read-only
  reviews both returned KEEP AS APPLIED. Its confirmation-word recommendation was
  NOT applied and is an open entry in TODO.md. Everything else it raised was
  judged not to need action.
live_authority:
  - web/i18n/ar.yaml
  - TODO.md
  - docs/PRODUCT.md
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not apply a recommendation from
> this file without checking `web/i18n/ar.yaml` and `TODO.md` first. What was acted on:
> the `page.policy.rightsDelete` fix, applied. What is still open: the confirmation-word
> decision, now a `TODO.md` entry. What was declined: the English rewrite, deliberately —
> both reviewers advised against churning draft policy copy for no reader benefit. Every
> heading is prefixed `[HISTORICAL]`.

# [HISTORICAL] First-pass Arabic QA: Account-Deletion Strings

Overall, the Arabic catalogue for the account-deletion and data-retention feature is of exceptionally high quality. It adheres strictly to formal Modern Standard Arabic (MSA), maintains the professional, sober tone demanded by `docs/PRODUCT.md` for regulatory and pharmaceutical professionals, and demonstrates impeccable Arabic grammar (notably employing the correct jussive form «ما لم تُلغِ» rather than colloquial or ungrammatical alternatives). It is very close to shippable. However, out of the 59 strings in scope (56 new, 3 modified), **only 1 string** carries a material, meaning-changing defect that alters legal/operational reality and must be corrected before sign-off. An additional **6 strings** involve product, UX, or register judgement calls (including the choice of confirmation word), and **7 strings** exhibit terminology divergences from established conventions elsewhere in `ar.yaml`. The remaining **45 strings** are verified clean. A human reviewer can thus focus deeply on roughly 10–14 strings rather than re-reading all 59.

---

## [HISTORICAL] Must fix before a human signs off

This section contains strings where the Arabic translation materially alters the operational or legal meaning of the English counterpart.

| Key                        | English                                                                                                                                                              | Arabic                                                                                                                                          | What is wrong                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Suggested correction                                                                                                                                                                                                                                                                                                           |
| :------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `page.policy.rightsDelete` | `"Delete individual conversations, all of them at once, or your entire account — account deletion carries a 30-day grace period during which you can still cancel."` | `"حذف محادثة واحدة أو جميع المحادثات دفعة واحدة، أو حذف حسابك بالكامل. عند حذف الحساب تبدأ فترة سماح مدتها 30 يومًا يمكنك خلالها إلغاء الطلب."` | The second sentence states: «عند حذف الحساب تبدأ فترة سماح مدتها 30 يومًا يمكنك خلالها إلغاء الطلب» (_"Upon deleting the account, a 30-day grace period begins during which you can cancel the request"_). Legally and technically, the account is **not** deleted when the grace period begins; deletion occurs only _after_ the 30 days expire. What happens at day zero is that the user **requests** deletion. Saying «عند حذف الحساب» implies the account is already deleted, which makes cancelling a "request" logically contradictory and misinforms the reader. Compare with the correct phrasing in `page.account.deletionLead` («عند طلب حذف حسابك تبدأ فترة سماح...») and `page.policy.retentionBody` («عند طلب الحذف تبدأ فترة سماح...»). | `"حذف محادثة واحدة أو جميع المحادثات دفعة واحدة، أو حذف حسابك بالكامل. عند طلب حذف الحساب تبدأ فترة سماح مدتها 30 يومًا يمكنك خلالها إلغاء الطلب."`<br><br>_(Alternative: `"حذف محادثة واحدة أو جميع المحادثات دفعة واحدة، أو حذف حسابك بالكامل — يتضمّن طلب حذف الحساب فترة سماح مدتها 30 يومًا يمكنك خلالها إلغاء الطلب."`)_ |

---

## [HISTORICAL] Worth a human's judgement

This section covers deliberate product decisions, UX friction mechanisms, register calls, and technical nuances where human discretion is required.

### 1. The Confirmation Word (`DELETE` vs `حذف`)

- **Keys:**
  - `page.account.deletionConfirmWord`:
    - **EN:** `"DELETE"`
    - **AR:** `"حذف"`
  - `page.account.deletionConfirmLabel`:
    - **EN:** `"Type DELETE to confirm"`
    - **AR:** `"اكتب «حذف» لتأكيد طلبك"`
- **Analysis:**
  In English, `"DELETE"` in uppercase is an intentional friction pattern. The reader must deliberately type six uppercase letters, requiring the Shift key or Caps Lock.
  In Arabic, script has no letter casing. `حذف` is a 3-letter common root (ح-ذ-ف) that serves as the ubiquitous label on standard delete buttons and icons across all Arabic software. It requires minimal typing effort and can easily be typed subconsciously or via auto-complete.
  Conversely, forcing an Arabic user to switch keyboard layouts to type Latin `DELETE` violates the core product principle (_"Arabic is not a translation layer... Full EN/AR parity with true RTL mirroring"_, `docs/PRODUCT.md:156,207`), particularly on mobile devices where switching input methods adds jarring friction.
- **Recommendation:**
  Replace `حذف` with **`حذف الحساب`** (_"Delete Account"_) or **`تأكيد الحذف`** (_"Confirm Deletion"_).
  `حذف الحساب` is specifically recommended: it explicitly identifies the destructive scope (the entire account, not just a message), requires deliberate two-word typing (10 characters including space), and provides meaningful cognitive friction while remaining natural, native Arabic.
  _Note:_ In `web/api/account.py:368-386`, `_expected_deletion_confirmations()` dynamically loads `page.account.deletionConfirmWord` from the YAML catalogues. Updating `deletionConfirmWord` in `ar.yaml` will automatically update both frontend validation and backend acceptance without code changes.

### 2. Unprompted Guidance in Admin Note

- **Key:** `page.account.deletionAdminNote`
  - **EN:** `"Self-serve deletion is not available to administrator accounts."`
  - **AR:** `"الحذف الذاتي للحساب غير متاح لحسابات المسؤولين. يُرجى التواصل مع مسؤول آخر."`
- **Analysis:**
  The Arabic text appends an extra sentence: «يُرجى التواصل مع مسؤول آخر.» (_"Please contact another administrator."_). This addition mirrors the API error message `runtime.profile.account.deletionAdminRefused` (_"Self-serve deletion is not available to administrator accounts. Ask another administrator."_). While practically helpful to an administrator viewing `/account`, it is an unprompted divergence from English `deletionAdminNote`.
- **Recommendation:**
  Human decision: either keep the helpful instruction and update the English catalogue for parity, or trim the Arabic string to exact parity:
  `"الحذف الذاتي للحساب غير متاح لحسابات المسؤولين."`

### 3. Hedging and Interrogative Tone in Retention Policy Heading

- **Key:** `page.policy.retentionStaysHeading`
  - **EN:** `"What remains after deletion"`
  - **AR:** `"ما الذي قد يبقى بعد الحذف؟"`
- **Analysis:**
  The English source is a definitive declarative heading (_"What remains after deletion"_). The Arabic adds «قد» (_"might / may"_) and a question mark (_"What might remain after deletion?"_). While question headings are common in consumer FAQs, in a binding regulatory and privacy policy under Saudi PDPL scrutiny, definitive phrasing provides clearer legal certainty.
- **Recommendation:**
  Consider adopting definitive phrasing without hedging:
  `"ما يبقى بعد حذف الحساب"` or `"ما يبقى بعد الحذف"`.

### 4. Cryptographic "Salts" Translation

- **Key:** `page.policy.retentionStaysBody`
  - **EN:** `"...The dormant research archive collects nothing while its salts are unset."`
  - **AR:** `"...ولا يجمع أرشيف الأبحاث أي بيانات ما دامت مفاتيحه غير مفعّلة."`
- **Analysis:**
  In the backend (`web/api/app.py:1858`), `salts` refers specifically to `ARCHIVE_OWNER_SALT` and `ARCHIVE_SESSION_SALT` — cryptographic salts used for one-way pseudonymization. The Arabic renders this as «مفاتيحه غير مفعّلة» (_"while its keys are inactive"_). Cryptographic salts are distinct from encryption keys (مفاتيح).
- **Recommendation:**
  For general readers, «مفاتيحه» is easily understood as configuration/keys. However, for a regulatory platform catering to compliance officers and auditors, technically accurate phrasing is preferable:
  `"...ما دامت قيم التمليح الخاصة به غير معيّنة."` or `"...ما دامت معطيات التمليح غير مضبوطة."`.

### 5. Native Alert Bidi Formatting and Untranslated Enum

- **Key:** `runtime.admin.deletions.confirmReconcile`
  - **EN:** `"Drive this account's deletion saga forward one pass (state: {state})? This can purge conversations and delete the sign-in."`
  - **AR:** `"هل تريد متابعة عملية حذف هذا الحساب من مرحلتها الحالية (الحالة: {state})؟ قد يؤدي ذلك إلى حذف المحادثات نهائيًا وإزالة بيانات تسجيل الدخول."`
- **Analysis:**
  This string is consumed by `window.confirm()` in `static/js/admin/handlers.js:1615`. Browser native alert dialogs render plain text without HTML `<bdi>` or CSS isolation.
  `{state}` is populated with raw English database enums (`requested`, `purging`, `purged`, `deleting_auth`, `completed`, `cancelled`).
  Placing an ASCII Latin token inside Arabic parentheses immediately preceding punctuation (`(الحالة: {state})؟`) can trigger bidirectional glyph confusion or parenthesis inversion in certain OS dialog renderers. Furthermore, an Arabic-speaking operator sees untranslated code tokens.
- **Recommendation:**
  Rephrase to avoid tight parenthesis clustering around the Latin placeholder:
  `"هل تريد متابعة عملية حذف هذا الحساب من مرحلتها الحالية، والحالة هي {state}؟ قد يؤدي ذلك إلى حذف المحادثات نهائيًا وإزالة بيانات تسجيل الدخول."`

---

## [HISTORICAL] Consistency notes

This section details terms in the deletion feature that diverge from established choices elsewhere in `web/i18n/ar.yaml`.

### 1. Notifications: «التنبيهات» vs «الإشعارات»

- **Deletion keys:**
  - `page.account.deletionStaysBody`: `"وسجلات التنبيهات المرتبطة برسالة المشغّل"`
  - `page.policy.retentionStaysBody`: `"وتبقى سجلات التنبيهات بمعرّف الحساب إلى جانب رسالة المشغّل."`
- **Compared against existing keys:**
  - `page.admin.tabs.notifications`: `"الإشعارات"`
  - `runtime.admin.audit.actionNotificationCreate`: `"أرسل إشعارًا"`
  - `runtime.admin.notifications.history.loadFailed`: `"تعذّر تحميل سجلّ الإشعارات."`
  - `runtime.admin.notifications.history.deleteConfirm`: `"حذف هذا الإشعار؟ لا يمكن التراجع عن هذا."`
- **Finding:**
  Across the entire application (the reader notification center, admin broadcast, and audit logs), the product strictly uses **«إشعار» / «الإشعارات»**. Using **«التنبيهات»** in the deletion copy introduces an unnecessary synonym for an established domain concept.
- **Recommendation:**
  Change «سجلات التنبيهات» to **«سجلات الإشعارات»** in both keys.

### 2. Audit Action Verb Structure: Nominal/Passive vs Active Past Verb

- **Deletion key:**
  - `runtime.admin.audit.actionDeletionReconcile`: `"تمت متابعة عملية حذف الحساب إلى المرحلة التالية"`
- **Compared against existing keys:**
  - `runtime.admin.audit.actionSettingsUpdate`: `"غيّر الإعدادات"`
  - `runtime.admin.audit.actionUserDisable`: `"عطّل الوصول للمحادثة"`
  - `runtime.admin.audit.actionUserEnable`: `"استعاد الوصول للمحادثة"`
  - `runtime.admin.audit.actionNotificationCreate`: `"أرسل إشعارًا"`
  - `runtime.admin.audit.actionTierCreate`: `"أنشأ فئة"`
  - `runtime.admin.audit.actionQuotaOverrideChange`: `"غيّر الرصيد اليومي لحساب"`
- **Finding:**
  Every existing audit action in `runtime.admin.audit.*` starts with an active 3rd-person singular masculine past verb denoting the operator's action (_"Changed..."_, _"Disabled..."_, _"Created..."_). `actionDeletionReconcile` is the only action framed as passive/periphrastic («تمت متابعة...»).
- **Recommendation:**
  Align with the audit catalogue convention:
  `"تابع مسار حذف حساب إلى المرحلة التالية"` or `"استكمل عملية حذف حساب"`.

### 3. Quota Overrides: «تجاوزات الحصة» vs «الرصيد الخاص»

- **Deletion key:**
  - `page.account.deletionGoesBody`: `"...إضافةً إلى البيانات التشغيلية المرتبطة بها مثل سجل آخر ظهور وتجاوزات الحصة."`
- **Compared against existing keys:**
  - `runtime.admin.account.overrideStandingLabel`: `"الرصيد الخاص"`
  - `runtime.admin.account.overrideLabel`: `"تجاوز خاص بهذا الحساب"`
  - `runtime.admin.account.quotaHint`: `"الفئة هي رصيد المجموعة، والرصيد الخاص لهذا الحساب وحده."`
  - `runtime.chat.quota.body`: `"لقد استخدمت كل رصيدك اليوم ({limit})."`
- **Finding:**
  The daily question limit is consistently translated as **«الرصيد»**, and per-account overrides are translated as **«الرصيد الخاص»** or **«تجاوز خاص»**. Introducing **«الحصة»** creates a disjointed terminology for the reader.
- **Recommendation:**
  Adjust to **«تجاوزات الرصيد الخاص»** or **«سجلات الرصيد الخاص»**.

### 4. "Chat" as a Verb in Grace Usability Lists

- **Deletion keys:**
  - `page.account.deletionLead`: `"واستخدام المحادثات وقراءتها وتصديرها"`
  - `page.account.deletionPendingBody`: `"واستخدام محادثاتك وقراءتها وتصديرها"`
  - `runtime.profile.account.deletionPendingBody`: `"واستخدام محادثاتك وقراءتها وتصديرها"`
  - `page.policy.retentionBody`: `"واستخدام المحادثات وقراءتها وتصديرها"`
- **Compared against existing keys:**
  - `runtime.chat.loginRequired`: `"يرجى تسجيل الدخول للمحادثة مع المساعد."`
  - `runtime.auth.accountDisabled`: `"تم إيقاف الوصول للمحادثة لهذا الحساب."`
  - `page.account.exportHint`: `"تنزيل كل محادثة أجريتها..."`
- **Finding:**
  In English, the copy lists active verbs: _"sign in, chat, read and export your conversations..."_. The Arabic translation turned "chat" into a noun and bundled it into «استخدام المحادثات / استخدام محادثاتك» (_"using your conversations"_). In Arabic, one does not "use" a conversation; one conducts or starts it.
- **Recommendation:**
  Use natural verbal phrasing:
  `"تسجيل الدخول وإجراء المحادثات وقراءتها وتصديرها"` or `"المحادثة وقراءة محادثاتك وتصديرها"`.

### 5. Data Purge Terminology (Positive Divergence Note)

- **Deletion keys:**
  - `page.account.deletionLead`: `"تُحذف محادثاتك نهائيًا"`
  - `runtime.admin.deletions.confirmReconcile`: `"حذف المحادثات نهائيًا"`
  - `runtime.admin.deletions.hint`: `"حذف المحادثات نهائيًا أولًا"`
  - `runtime.profile.account.deletionCancelUnavailable`: `"فقد حُذفت المحادثات نهائيًا بالفعل."`
- **Compared against existing keys:**
  - `runtime.admin.notifications.history.purge`: `"تطهير"`
  - `runtime.admin.audit.actionNotificationPurge`: `"طهّر إشعارًا"`
- **Finding:**
  In `notifications.history`, "purge" was previously translated literally as «تطهير» (which in a Saudi healthcare context primarily connotes medical/hygienic disinfection). In the new deletion feature, the translator correctly chose **«حذف نهائيًا»** (_"permanently delete"_), which is the standard, accurate term for permanent data erasure.
- **Recommendation:**
  Retain **«حذف نهائيًا»** in the deletion feature. In a future cleanup pass, `notifications.history` should be updated to match this superior phrasing.

---

## [HISTORICAL] Clean

**45 strings** out of the 59 in scope were thoroughly reviewed and found to be completely accurate, with zero meaning, consistency, register, or placeholder issues:

`page.account.deletionCancel`, `page.account.deletionCancelling`, `page.account.deletionGoesLabel`, `page.account.deletionHeading`, `page.account.deletionInProgressBody`, `page.account.deletionInProgressTitle`, `page.account.deletionPasswordHint`, `page.account.deletionPasswordLabel`, `page.account.deletionPendingTitle`, `page.account.deletionRequest`, `page.account.deletionRequestSaving`, `page.account.deletionStaysLabel`, `page.admin.tabs.deletions`, `page.policy.retentionBodyNoSelfServe`, `page.policy.rightsDeleteNoSelfServe`, `runtime.admin.deletions.columnAccount`, `runtime.admin.deletions.columnActions`, `runtime.admin.deletions.columnAttempts`, `runtime.admin.deletions.columnGrace`, `runtime.admin.deletions.columnLastError`, `runtime.admin.deletions.columnRequested`, `runtime.admin.deletions.columnState`, `runtime.admin.deletions.deletion_terminal`, `runtime.admin.deletions.empty`, `runtime.admin.deletions.hint`, `runtime.admin.deletions.loadFailed`, `runtime.admin.deletions.no_such_deletion`, `runtime.admin.deletions.outcomeAmbiguous`, `runtime.admin.deletions.outcomeCompleted`, `runtime.admin.deletions.outcomeFailed`, `runtime.admin.deletions.outcomeUnclaimed`, `runtime.admin.deletions.reconcile`, `runtime.admin.deletions.reconcileFailed`, `runtime.profile.account.consentGrantPendingDeletion`, `runtime.profile.account.deletionAdminRefused`, `runtime.profile.account.deletionAlreadyDeleted`, `runtime.profile.account.deletionCancelFailed`, `runtime.profile.account.deletionCancelUnavailable`, `runtime.profile.account.deletionCancelled`, `runtime.profile.account.deletionInProgressBody`, `runtime.profile.account.deletionRequestFailed`, `runtime.profile.account.deletionRequested`, `runtime.profile.account.deletionStatusFailed`, `runtime.profile.account.deletionStepUpFailed`, `runtime.auth.alreadyRegistered`.
