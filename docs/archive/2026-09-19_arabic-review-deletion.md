---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-19
supersedes_note: >
  The working sheet for the human Arabic review of the account-deletion and
  retention copy. The review is COMPLETE and applied; `web/i18n/ar.yaml` is the
  authority and this is only the trail. One string it signed off was corrected
  afterwards — see the QA report archived beside it.
live_authority:
  - web/i18n/ar.yaml
  - docs/PRODUCT.md
---

> [!CAUTION]
> **You are reading history, not a specification.** The strings below were correct
> when this sheet was written. `web/i18n/ar.yaml` is the authority and has moved on:
> `page.policy.rightsDelete` was corrected on 2026-09-19 after this review signed it
> off. Every heading is prefixed `[HISTORICAL]`.

# [HISTORICAL] Arabic review — account deletion & privacy copy

56 new and 3 changed strings, all reviewed by a human across two rounds.

One suggestion was **not** taken: `runtime.admin.deletions.deletion_terminal` was proposed as
"اكتملت عملية الحذف بالفعل" (already _completed_), but that message also fires for a
**cancelled** saga — `_TERMINAL_DELETION_STATES = {completed, cancelled}`
(`web/api/admin.py:1263`) — so it would tell an operator a deletion completed when it was
called off. It keeps "انتهت" (_finished_), which covers both.

Keys must stay identical across the two files or the parity test fails.

## [HISTORICAL] New strings

### `page.account.deletionAdminNote`

**EN:** Self-serve deletion is not available to administrator accounts.

**AR:** الحذف الذاتي للحساب غير متاح لحسابات المسؤولين. يُرجى التواصل مع مسؤول آخر.

### `page.account.deletionCancel`

**EN:** Cancel the deletion

**AR:** إلغاء طلب الحذف

### `page.account.deletionCancelling`

**EN:** Cancelling…

**AR:** جارٍ إلغاء طلب الحذف…

### `page.account.deletionConfirmLabel`

**EN:** Type DELETE to confirm

**AR:** اكتب «حذف» لتأكيد طلبك

### `page.account.deletionConfirmWord`

**EN:** DELETE

**AR:** حذف

### `page.account.deletionGoesBody`

**EN:** Your login identity, your profile (name, age, organization, specialization, consent record), every conversation, and the records derived from them (last-seen markers, quota overrides).

**AR:** بيانات تسجيل الدخول، وملفك الشخصي بما في ذلك الاسم والعمر والجهة والتخصص وسجل الموافقات، وجميع محادثاتك، إضافةً إلى البيانات التشغيلية المرتبطة بها مثل سجل آخر ظهور وتجاوزات الحصة.

### `page.account.deletionGoesLabel`

**EN:** What goes

**AR:** ما الذي سيتم حذفه؟

### `page.account.deletionHeading`

**EN:** Delete your account

**AR:** حذف حسابك

### `page.account.deletionInProgressBody`

**EN:** This deletion is past the point where it can be cancelled — the conversations have been purged or the sign-in is being removed. There is nothing left to cancel here, and no new request is needed.

**AR:** تجاوزت عملية الحذف المرحلة التي يمكن فيها إلغاؤها؛ فقد حُذفت المحادثات نهائيًا أو تجري حاليًا إزالة بيانات تسجيل الدخول. لم يعد هناك ما يمكن إلغاؤه، ولا حاجة إلى تقديم طلب حذف جديد.

### `page.account.deletionInProgressTitle`

**EN:** Deletion in progress

**AR:** الحذف جارٍ

### `page.account.deletionLead`

**EN:** Requesting deletion starts a 30-day grace period. During grace your account stays fully usable — sign in, chat, read, export, change your profile, and cancel at any time. The one exception is granting new marketing consent, which stays off while deletion is pending. When grace ends, your conversations are permanently purged and your login identity and profile are deleted.

**AR:** عند طلب حذف حسابك تبدأ فترة سماح مدتها 30 يومًا. خلال هذه الفترة يظل حسابك متاحًا للاستخدام بشكل كامل، فيمكنك تسجيل الدخول واستخدام المحادثات وقراءتها وتصديرها وتعديل ملفك الشخصي وإلغاء طلب الحذف في أي وقت. الاستثناء الوحيد هو أنه لن يكون بإمكانك منح موافقة تسويقية جديدة أثناء انتظار الحذف. بعد انتهاء فترة السماح تُحذف محادثاتك نهائيًا، ثم تُحذف بيانات تسجيل الدخول وملفك الشخصي.

### `page.account.deletionPasswordHint`

**EN:** Anyone holding your signed-in session could otherwise delete your account — for example on a shared computer — so we ask for your password as well.

**AR:** نطلب كلمة مرورك للتأكد من أنك صاحب الحساب، ولمنع أي شخص لديه وصول مؤقت إلى جلستك — على جهاز مشترك مثلًا — من حذف حسابك دون إذنك.

### `page.account.deletionPasswordLabel`

**EN:** Current password

**AR:** كلمة المرور الحالية

### `page.account.deletionPendingBody`

**EN:** Your account will be permanently deleted on {date}, unless you cancel first. Until then your account stays fully usable — sign in, chat, read and export your conversations, change your profile, and cancel at any time. (Granting new marketing consent stays off while deletion is pending.)

**AR:** سيُحذف حسابك نهائيًا في {date} ما لم تُلغِ طلب الحذف قبل ذلك. وحتى ذلك الوقت يظل حسابك متاحًا للاستخدام، فيمكنك تسجيل الدخول واستخدام محادثاتك وقراءتها وتصديرها وتعديل ملفك الشخصي وإلغاء طلب الحذف في أي وقت. لن يكون بإمكانك منح موافقة تسويقية جديدة أثناء انتظار الحذف.

### `page.account.deletionPendingTitle`

**EN:** Deletion requested

**AR:** طلب حذف الحساب قيد الانتظار

### `page.account.deletionRequest`

**EN:** Request deletion

**AR:** طلب حذف الحساب

### `page.account.deletionRequestSaving`

**EN:** Requesting…

**AR:** جارٍ إرسال طلب الحذف…

### `page.account.deletionStaysBody`

**EN:** Administrative records written before the deletion — which can include an email address, for example when an operator changed one — a ledger entry holding only an identifier and timestamps, notification records beside an operator's message, backup copies this deletion does not reach and for which no retention period is stated, the model provider's own prompt retention, and server logs. The full list is in the privacy policy.

**AR:** تبقى السجلات الإدارية المنشأة قبل الحذف، وقد تتضمّن عنوان بريد إلكتروني — كما في حالة تغيير المشغّل لعنوان بريد حساب. ويبقى سجل طلب الحذف الذي لا يتضمّن سوى معرّف وطوابع زمنية، وسجلات التنبيهات المرتبطة برسالة المشغّل، والنسخ الاحتياطية التي لا يصل إليها هذا الحذف والتي لا توجد لها مدة احتفاظ معلنة، وما يحتفظ به مزوّد النموذج من موجّهات أُرسلت إليه، وسجلات الخادم. القائمة الكاملة في سياسة الخصوصية.

### `page.account.deletionStaysLabel`

**EN:** What stays

**AR:** ما الذي يبقى؟

### `page.admin.tabs.deletions`

**EN:** Deletions

**AR:** عمليات الحذف

### `page.policy.retentionBodyNoSelfServe`

**EN:** Your account and conversations are kept for as long as your account exists. You can delete individual conversations or all of them at any time from your account page. Deleting your account itself is not yet self-service: send the request through the product's usual support channel.

**AR:** يُحتفَظ بحسابك ومحادثاتك ما دام حسابك قائمًا. يمكنك حذف محادثة واحدة أو جميع محادثاتك في أي وقت من صفحة حسابك. أما حذف الحساب بالكامل فليس متاحًا ذاتيًا حاليًا؛ لطلب ذلك، تواصل معنا عبر قناة الدعم المعتادة للمنتج.

### `page.policy.retentionStaysBody`

**EN:** Even after your account is deleted, some traces remain. Administrative records written before the deletion are kept — an operator email change, for example, records the old and new email address beside the account identifier in the append-only audit log; a deletion ledger entry holding only an account identifier and timestamps is kept; notification records keep a bare account identifier beside an operator's message; backup copies are not reached by this deletion, and no retention period is stated for them; the AI model provider retains prompts sent to it under its own policy; and server logs persist, including conversation access paths. The in-memory conversation window clears when the server worker restarts, not at the moment of deletion. The dormant research archive collects nothing while its salts are unset.

**AR:** حتى بعد حذف حسابك تبقى بعض الآثار المحدودة لأغراض إدارية أو تقنية. تبقى السجلات الإدارية المنشأة قبل الحذف، وقد تتضمّن عنوان بريد إلكتروني: فتغيير المشغّل لعنوان بريد حساب يسجّل العنوان القديم والجديد إلى جانب معرّف الحساب في سجل تدقيق لا يُحذف منه شيء. ويبقى سجل طلب الحذف الذي لا يتضمّن سوى معرّف الحساب وطوابع زمنية، وتبقى سجلات التنبيهات بمعرّف الحساب إلى جانب رسالة المشغّل. ولا يصل هذا الحذف إلى النسخ الاحتياطية، ولا توجد لها مدة احتفاظ معلنة. وقد يحتفظ مزوّد نموذج الذكاء الاصطناعي بالموجّهات المرسلة إليه وفق سياسته الخاصة. وتبقى سجلات الخادم، بما فيها مسارات الوصول إلى المحادثات. أما نافذة المحادثة المحفوظة في ذاكرة الخادم فتُمسح عند إعادة تشغيل عملية الخادم، لا لحظة حذف الحساب. ولا يجمع أرشيف الأبحاث أي بيانات ما دامت مفاتيحه غير مفعّلة.

### `page.policy.retentionStaysHeading`

**EN:** What remains after deletion

**AR:** ما الذي قد يبقى بعد الحذف؟

### `page.policy.rightsDeleteNoSelfServe`

**EN:** Delete individual conversations, or all of them at once.

**AR:** حذف محادثة واحدة أو جميع المحادثات دفعة واحدة.

### `runtime.admin.audit.actionDeletionReconcile`

**EN:** Drove a deletion saga forward

**AR:** تمت متابعة عملية حذف الحساب إلى المرحلة التالية

### `runtime.admin.deletions.columnAccount`

**EN:** Account

**AR:** الحساب

### `runtime.admin.deletions.columnActions`

**EN:**

**AR:**

### `runtime.admin.deletions.columnAttempts`

**EN:** Attempts

**AR:** عدد المحاولات

### `runtime.admin.deletions.columnGrace`

**EN:** Grace until

**AR:** انتهاء فترة السماح

### `runtime.admin.deletions.columnLastError`

**EN:** Last error

**AR:** آخر خطأ

### `runtime.admin.deletions.columnRequested`

**EN:** Requested

**AR:** تاريخ الطلب

### `runtime.admin.deletions.columnState`

**EN:** State

**AR:** الحالة

### `runtime.admin.deletions.confirmReconcile`

**EN:** Drive this account's deletion saga forward one pass (state: {state})? This can purge conversations and delete the sign-in.

**AR:** هل تريد متابعة عملية حذف هذا الحساب من مرحلتها الحالية (الحالة: {state})؟ قد يؤدي ذلك إلى حذف المحادثات نهائيًا وإزالة بيانات تسجيل الدخول.

### `runtime.admin.deletions.deletion_terminal`

**EN:** That deletion is already finished — nothing left to drive.

**AR:** انتهت عملية الحذف بالفعل، ولا يلزم اتخاذ أي إجراء.

### `runtime.admin.deletions.empty`

**EN:** No deletions in flight.

**AR:** لا توجد عمليات حذف جارية.

### `runtime.admin.deletions.hint`

**EN:** Accounts with a deletion in flight, newest request first. Reconciling drives one stuck saga through the same steps the automatic timer runs — purge, then delete the sign-in. Completed and cancelled rows need nothing.

**AR:** الحسابات التي توجد لها عمليات حذف جارية، مرتبة حسب الأحدث طلبًا. تتيح «متابعة العملية» استكمال أي عملية حذف متوقفة عبر نفس الخطوات التي ينفذها النظام تلقائيًا: حذف المحادثات نهائيًا أولًا، ثم إزالة بيانات تسجيل الدخول. لا يلزم اتخاذ أي إجراء للعمليات المكتملة أو الملغاة.

### `runtime.admin.deletions.loadFailed`

**EN:** Could not load the deletion ledger.

**AR:** تعذّر تحميل سجل عمليات الحذف.

### `runtime.admin.deletions.no_such_deletion`

**EN:** That deletion no longer exists.

**AR:** عملية الحذف هذه لم تعد موجودة.

### `runtime.admin.deletions.outcomeAmbiguous`

**EN:** The outcome is unknown — the timer will look again.

**AR:** تعذّر تحديد نتيجة العملية. سيعيد النظام التحقق منها تلقائيًا.

### `runtime.admin.deletions.outcomeCompleted`

**EN:** Deletion completed.

**AR:** اكتملت عملية الحذف.

### `runtime.admin.deletions.outcomeFailed`

**EN:** The drive failed — check the ledger's last error.

**AR:** تعذّرت متابعة عملية الحذف. يُرجى مراجعة آخر خطأ في السجل.

### `runtime.admin.deletions.outcomeUnclaimed`

**EN:** Another driver holds this saga — nothing was done.

**AR:** تتم معالجة هذه العملية حاليًا بواسطة معالج آخر، لذلك لم يتم اتخاذ أي إجراء.

### `runtime.admin.deletions.reconcile`

**EN:** Reconcile

**AR:** متابعة العملية

### `runtime.admin.deletions.reconcileFailed`

**EN:** Could not drive that deletion.

**AR:** تعذّرت متابعة عملية الحذف.

### `runtime.profile.account.consentGrantPendingDeletion`

**EN:** You cannot grant marketing consent while your account has a deletion in flight. Withdrawing consent stays available at any time.

**AR:** لا يمكنك منح موافقة تسويقية جديدة أثناء انتظار حذف حسابك. ويمكنك سحب موافقتك الحالية في أي وقت.

### `runtime.profile.account.deletionAdminRefused`

**EN:** Self-serve deletion is not available to administrator accounts. Ask another administrator.

**AR:** الحذف الذاتي للحساب غير متاح لحسابات المسؤولين. يُرجى التواصل مع مسؤول آخر.

### `runtime.profile.account.deletionAlreadyDeleted`

**EN:** This account has already been deleted.

**AR:** تم حذف هذا الحساب بالفعل.

### `runtime.profile.account.deletionCancelFailed`

**EN:** Could not cancel the deletion. Please try again.

**AR:** تعذّر إلغاء طلب الحذف. يُرجى المحاولة مرة أخرى.

### `runtime.profile.account.deletionCancelUnavailable`

**EN:** This deletion can no longer be cancelled — its conversations have already been purged.

**AR:** لم يعد من الممكن إلغاء طلب الحذف، فقد حُذفت المحادثات نهائيًا بالفعل.

### `runtime.profile.account.deletionCancelled`

**EN:** The deletion has been cancelled. Your account is fully restored.

**AR:** تم إلغاء طلب الحذف، وعاد حسابك إلى حالته الطبيعية بالكامل.

### `runtime.profile.account.deletionInProgressBody`

**EN:** This deletion is past the point where it can be cancelled — the conversations have been purged or the sign-in is being removed. There is nothing left to cancel here, and no new request is needed.

**AR:** تجاوزت عملية الحذف المرحلة التي يمكن فيها إلغاؤها؛ فقد حُذفت المحادثات نهائيًا أو تجري حاليًا إزالة بيانات تسجيل الدخول. لم يعد هناك ما يمكن إلغاؤه، ولا حاجة إلى تقديم طلب حذف جديد.

### `runtime.profile.account.deletionPendingBody`

**EN:** Your account will be permanently deleted on {date}, unless you cancel first. Until then your account stays fully usable — sign in, chat, read and export your conversations, change your profile, and cancel at any time. (Granting new marketing consent stays off while deletion is pending.)

**AR:** سيُحذف حسابك نهائيًا في {date} ما لم تُلغِ طلب الحذف قبل ذلك. وحتى ذلك الوقت يظل حسابك متاحًا للاستخدام، فيمكنك تسجيل الدخول واستخدام محادثاتك وقراءتها وتصديرها وتعديل ملفك الشخصي وإلغاء طلب الحذف في أي وقت. لن يكون بإمكانك منح موافقة تسويقية جديدة أثناء انتظار الحذف.

### `runtime.profile.account.deletionRequestFailed`

**EN:** Could not request deletion. Please try again.

**AR:** تعذّر إرسال طلب الحذف. يُرجى المحاولة مرة أخرى.

### `runtime.profile.account.deletionRequested`

**EN:** Deletion requested. Your account stays usable for 30 days, and you can cancel at any time from this page.

**AR:** تم إرسال طلب حذف حسابك. سيظل الحساب متاحًا للاستخدام لمدة 30 يومًا، ويمكنك إلغاء الطلب في أي وقت من هذه الصفحة.

### `runtime.profile.account.deletionStatusFailed`

**EN:** Could not check the deletion status. Please reload the page.

**AR:** تعذّر التحقق من حالة طلب الحذف. يُرجى إعادة تحميل الصفحة.

### `runtime.profile.account.deletionStepUpFailed`

**EN:** That password was not right. Check it and try again.

**AR:** كلمة المرور غير صحيحة. تحقّق منها وحاول مرة أخرى.

## [HISTORICAL] Changed strings

### `page.policy.retentionBody`

**EN (was):** Your account and conversations are kept for as long as your account exists. You can delete individual conversations or all of them at any time from your account page; deleting your account entirely is not yet self-service — contact us if you need it.

**EN (now):** Your account and conversations are kept for as long as your account exists. You can delete individual conversations or all of them at any time from your account page, and you can delete your entire account yourself: requesting deletion starts a 30-day grace period during which your account stays fully usable — sign in, chat, read and export your conversations, change your profile, and cancel at any time — except granting new marketing consent, which stays off while deletion is pending. When the 30 days end, your conversations are permanently purged and your login identity and profile are deleted.

**AR (now):** نحتفظ بحسابك ومحادثاتك ما دام حسابك قائمًا. يمكنك حذف محادثة واحدة أو جميع محادثاتك في أي وقت من صفحة حسابك، كما يمكنك طلب حذف حسابك بالكامل بنفسك. عند طلب الحذف تبدأ فترة سماح مدتها 30 يومًا يظل حسابك خلالها متاحًا للاستخدام بشكل كامل، فيمكنك تسجيل الدخول واستخدام المحادثات وقراءتها وتصديرها وتعديل ملفك الشخصي وإلغاء طلب الحذف في أي وقت. الاستثناء الوحيد هو أنه لن يكون بإمكانك منح موافقة تسويقية جديدة أثناء انتظار الحذف. بعد انتهاء فترة السماح تُحذف محادثاتك نهائيًا، ثم تُحذف بيانات تسجيل الدخول وملفك الشخصي.

### `page.policy.rightsDelete`

**EN (was):** Delete individual conversations, or all of them at once.

**EN (now):** Delete individual conversations, all of them at once, or your entire account — account deletion carries a 30-day grace period during which you can still cancel.

**AR (now):** حذف محادثة واحدة أو جميع المحادثات دفعة واحدة، أو حذف حسابك بالكامل. عند حذف الحساب تبدأ فترة سماح مدتها 30 يومًا يمكنك خلالها إلغاء الطلب.

### `runtime.auth.alreadyRegistered`

**EN (was):** This email is already registered. Please log in.

**EN (now):** This email address is already linked to an account. Please log in instead of creating a new one.

**AR (now):** هذا البريد الإلكتروني مرتبط بحساب موجود. يُرجى تسجيل الدخول بدلًا من إنشاء حساب جديد.
