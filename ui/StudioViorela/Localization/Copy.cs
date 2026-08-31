namespace StudioViorela.Localization;

/// <summary>
/// Every string the interface shows, Romanian first, English second.
///
/// Romanian leads on every line because it is the client's language and the one
/// the studio is actually run in; English exists so the product can be shown to
/// somebody who does not read Romanian. What the agent *generates* follows the
/// same switch, through `content_studio.language` on the server — but the method
/// behind it stays Romanian, and so do the pillar, source and format values sent
/// to the API. Only the labels change; see <see cref="Values"/>.
/// </summary>
public static class Copy
{
    // ---- shell and brand ----------------------------------------------------
    public static readonly Phrase BrandName = new("Studio Viorela", "Studio Viorela");
    public static readonly Phrase BrandTagline =
        new("Conținut care sună ca tine", "Content that sounds like you");
    public static readonly Phrase HomeAria =
        new("Studio Viorela, pagina principală", "Studio Viorela, home");

    // ---- the access gate ----------------------------------------------------
    public static readonly Phrase CheckingAccess =
        new("Se verifică accesul…", "Checking access…");
    public static readonly Phrase SignInLede =
        new("Conținut care sună ca tine.", "Content that sounds like you.");
    public static readonly Phrase SignInWithGoogle =
        new("Intră cu Google", "Sign in with Google");
    // The studio account: a username and a password Sorin issues from the Entra
    // external tenant. Named for what the person holds, not for the product
    // behind it — nobody signing in thinks of themselves as having "an Entra".
    public static readonly Phrase SignInWithStudioAccount =
        new("Intră cu user și parolă", "Sign in with username and password");
    public static readonly Phrase SignInOr = new("sau", "or");
    public static readonly Phrase InvitedOnly =
        new("Doar conturile invitate au acces.", "Only invited accounts have access.");
    public static readonly Phrase DeniedTitle =
        new("Acest cont nu are acces", "This account has no access");
    // Provider-neutral since the studio has two doors: naming Google here would
    // be wrong for half the people who can reach this screen.
    public static readonly Phrase DeniedLede = new(
        "Ai intrat cu un cont care nu e pe lista studioului.",
        "You signed in with an account that is not on the studio list.");
    public static readonly Phrase DeniedCta =
        new("Ieși și încearcă alt cont", "Sign out and try another account");

    // ---- identity strip -----------------------------------------------------
    public static readonly Phrase LocalSession = new("Sesiune locală", "Local session");
    public static readonly Phrase LocalMode = new("mod local", "local mode");
    public static readonly Phrase AuthorizedAccount =
        new("cont autorizat", "authorized account");
    // Spelled out rather than an icon: a glyph nobody recognises is not a way out.
    public static readonly Phrase SignOut = new("Ieși din cont", "Log out");

    // ---- language switch ----------------------------------------------------
    public static readonly Phrase LanguageAria =
        new("Alege limba interfeței", "Choose the interface language");
    // Endonyms on purpose: a language is named in its own language, so somebody
    // who reads neither can still find the one they do.
    public const string RomanianName = "Română";
    public const string EnglishName = "English";

    // ---- navigation ---------------------------------------------------------
    public static readonly Phrase NavAria = new("Navigare principală", "Main navigation");
    public static readonly Phrase NavGroupWork = new("Lucrezi", "Your work");
    public static readonly Phrase NavGroupYou = new("Ce te reprezintă", "What defines you");
    public static readonly Phrase NavGenerator = new("Generator", "Generator");
    public static readonly Phrase NavSaved = new("Salvate", "Saved");
    public static readonly Phrase NavProfile = new("Profil", "Profile");
    public static readonly Phrase NavLibrary = new("Materiale", "Materials");

    // ---- shared controls ----------------------------------------------------
    public static readonly Phrase DismissMessage =
        new("Închide mesajul", "Dismiss message");
    public static readonly Phrase Optional = new("(opțional)", "(optional)");
    public static readonly Phrase Preparing = new("Se pregătește…", "Preparing…");
    public static readonly Phrase Confirm = new("Confirmă", "Confirm");
    public static readonly Phrase Applying = new("Se aplică…", "Applying…");
    public static readonly Phrase Cancel = new("Renunță", "Cancel");
    public static readonly Phrase NotNow = new("Nu acum", "Not now");
    public static readonly Phrase Stop = new("Oprește", "Stop");
    public static readonly Phrase TryAgain = new("Încearcă din nou", "Try again");
    public static readonly Phrase LiveReconnected = new(
        "Conexiunea live se reface automat. Lotul rămâne salvat.",
        "The live connection restores itself. The batch stays saved.");

    // ---- request failures ---------------------------------------------------
    public static readonly Phrase EmptyResponse = new(
        "Serverul a răspuns fără conținut.", "The server answered with no content.");
    public static readonly Phrase RequestFailed =
        new("Cererea nu a reușit.", "The request did not succeed.");
    public static readonly Phrase IncompleteData = new(
        "Datele trimise nu sunt complete.", "The data sent is not complete.");
    public static readonly Phrase StillMissing =
        new("Mai e de completat", "Still to fill in");

    // ---- approval panel -----------------------------------------------------
    public static readonly Phrase ApprovalEyebrow =
        new("Confirmare necesară", "Confirmation needed");
    public static readonly Phrase ApprovalDefaultTitle =
        new("Modificarea este pregătită", "The change is ready");
    public static readonly Phrase ApprovalDefaultMessage = new(
        "Profilul nu se schimbă până când alegi explicit „Confirmă”.",
        "The profile does not change until you explicitly choose “Confirm”.");

    // ---- generator page -----------------------------------------------------
    public static readonly Phrase GeneratorTab =
        new("Generator · Studio Viorela", "Generator · Studio Viorela");
    public static readonly Phrase GeneratorEyebrow = new("Planifică simplu", "Plan simply");
    public static readonly Phrase GeneratorHeading =
        new("Ce vrei să creezi astăzi?", "What do you want to create today?");
    public static readonly Phrase GeneratorLede = new(
        "Primești întâi 10 idei clare. Deschizi ideea care îți place și ți-o scriu întreagă, cu 5 hook-uri și conținutul complet.",
        "You get 10 clear ideas first. Open the one you like and I write it in full, with 5 hooks and the complete content.");
    public static readonly Phrase GeneratorStepChip = new(
        "10 titluri întâi · detaliile la cerere",
        "10 titles first · details on demand");

    public static readonly Phrase FieldSource = new("Sursa ideilor", "Idea source");
    public static readonly Phrase DevelopHint = new(
        "Apasă ca să scriu cele 5 variante pentru ideea asta.",
        "Tap to have me write the 5 variants for this idea.");
    public static readonly Phrase DevelopWorking = new(
        "Scriu cele 5 variante…", "Writing the 5 variants…");
    public static readonly Phrase DevelopRetry = new("Încearcă din nou", "Try again");
    public static readonly Phrase FieldPillar = new("Pilon", "Pillar");
    public static readonly Phrase FieldFormat = new("Format", "Format");

    public static readonly Phrase LibraryLoading =
        new("Se încarcă biblioteca…", "Loading the library…");
    public static readonly Phrase SummarySuffix = new(" · rezumat", " · summary");

    public static readonly Phrase FocusLabel = new(
        "Ce focus ai pentru săptămâna aceasta?", "What is your focus this week?");
    public static readonly Phrase FocusPlaceholder = new(
        "De exemplu: cum recunoști că ai intrat din nou în people pleasing",
        "For example: how to tell you have slipped back into people pleasing");
    public static readonly Phrase AgentBringsItsOwnMaterial = new(
        "Agentul își caută singur materialul în sursa aleasă — inclusiv cărțile potrivite, când sursa e Cărți.",
        "The agent gathers its own material from the chosen source — including the fitting books when the source is Books.");
    public static readonly Phrase PreparingBatch =
        new("Se pregătește lotul…", "Preparing the batch…");
    public static readonly Phrase GenerateTen =
        new("Generează 10 idei", "Generate 10 ideas");

    public static readonly Phrase ReplaceAria =
        new("Înlocuiește lotul curent", "Replace the current batch");
    public static readonly Phrase ReplaceEyebrow =
        new("Ai deja un lot curent", "You already have a current batch");
    public static readonly Phrase ReplaceHeading =
        new("Vrei să-l înlocuiești?", "Do you want to replace it?");
    public static readonly Phrase ReplaceBody = new(
        "Lotul existent nu va mai fi curent. Postările deja salvate nu sunt afectate.",
        "The existing batch stops being the current one. Posts you already saved are not affected.");
    public static readonly Phrase ReplaceKeep = new("Păstrează-l", "Keep it");
    public static readonly Phrase ReplaceConfirm =
        new("Înlocuiește și generează", "Replace and generate");

    public static readonly Phrase LoadingBatch =
        new("Se recuperează lotul curent…", "Loading the current batch…");
    public static readonly Phrase IdeasAria =
        new("Ideile generate", "The generated ideas");
    public static readonly Phrase CurrentBatch =
        new("Lotul tău curent", "Your current batch");
    public static readonly Phrase YourIdeas = new("Ideile tale", "Your ideas");
    public static readonly Phrase PreparingTitle =
        new("Se pregătește titlul…", "Preparing the title…");
    public static readonly Phrase NanoWorking = new(
        "modelul lucrează la prima listă", "the model is working on the first list");

    // A batch that ended with nothing used to render ten of the waiting cards
    // above, spinning for ever. Seen on the deployed studio on 2026-08-31: the
    // run failed in a third of a second for a missing sandbox key, and the only
    // thing that said so was one line of status text above ten spinners. She
    // read the spinners. A finished batch with nothing in it says so plainly and
    // offers the one thing that helps.
    public static readonly Phrase EmptyBatchHeading = new(
        "Lotul nu a produs niciun titlu.", "The batch produced no titles.");
    public static readonly Phrase EmptyBatchBody = new(
        "S-a oprit înainte să scrie ceva. Nu s-a salvat nimic și nu s-a pierdut nimic.",
        "It stopped before it wrote anything. Nothing was saved and nothing was lost.");
    public static readonly Phrase EmptyBatchRetry =
        new("Încearcă din nou", "Try again");
    public static readonly Phrase HookTypesAria = new("Tipuri de hook", "Hook types");
    public static readonly Phrase ChosenVariantTitle =
        new("Variantă aleasă", "Chosen variant");

    public static readonly Phrase FieldTitle = new("Titlu", "Title");
    public static readonly Phrase FieldHookType = new("Tip de hook", "Hook type");
    public static readonly Phrase LabelHook = new("Hook", "Hook");
    public static readonly Phrase LabelScript = new("Script / conținut", "Script / content");
    public static readonly Phrase LabelProduction = new("Producție", "Production");
    public static readonly Phrase LabelCaption = new("Caption", "Caption");
    public static readonly Phrase LabelCta = new("CTA", "CTA");
    public static readonly Phrase LabelHashtags = new("Hashtaguri", "Hashtags");
    public static readonly Phrase LabelSource = new("Sursă", "Source");
    public static readonly Phrase ChosenVariant =
        new("✓ Varianta aleasă", "✓ Chosen variant");
    public static readonly Phrase ChooseVariant =
        new("Alege această variantă", "Choose this variant");

    public static readonly Phrase SaveAria = new(
        "Postările pregătite pentru salvare", "The posts ready to be saved");
    public static readonly Phrase ReadyToSave = new("Gata de salvat", "Ready to save");
    public static readonly Phrase FinalPosts = new("Postările finale", "The final posts");
    public static readonly Phrase SaveLede = new(
        "Bifează ce vrei să păstrezi. Se salvează toate odată sau niciuna, după confirmarea ta.",
        "Tick what you want to keep. They are saved all at once or not at all, after you confirm.");
    public static readonly Phrase NothingWithoutYou = new(
        "Nimic nu se scrie fără confirmarea ta.",
        "Nothing is written without your confirmation.");
    public static readonly Phrase SaveApprovalTitle =
        new("Salvezi postările alese?", "Save the posts you chose?");
    public static readonly Phrase SaveApprovalMessage = new(
        "Ajung în „Salvate” numai după ce apeși Confirmă. Se salvează toate odată sau niciuna.",
        "They reach “Saved” only after you press Confirm. All at once, or not at all.");
    public static readonly Phrase SaveCancelled = new(
        "Salvarea a fost anulată. Nimic nu s-a scris.",
        "The save was cancelled. Nothing was written.");

    // ---- saved page ---------------------------------------------------------
    public static readonly Phrase SavedTab =
        new("Salvate · Studio Viorela", "Saved · Studio Viorela");
    public static readonly Phrase SavedEyebrow = new("Colecția ta", "Your collection");
    public static readonly Phrase SavedHeading = new("Postări salvate", "Saved posts");
    public static readonly Phrase SavedLede = new(
        "Aici sunt numai postările finale pe care ai ales explicit să le păstrezi.",
        "These are only the final posts you explicitly chose to keep.");
    public static readonly Phrase SavedLoading =
        new("Se încarcă postările salvate…", "Loading the saved posts…");
    public static readonly Phrase SavedEmptyHeading =
        new("Încă nu ai postări salvate", "You have no saved posts yet");
    public static readonly Phrase SavedEmptyBody = new(
        "După ce dezvolți o idee și alegi o variantă, o poți salva și găsi aici.",
        "Once you develop an idea and choose a variant, you can save it and find it here.");
    public static readonly Phrase SavedEmptyCta =
        new("Creează prima idee", "Create your first idea");
    public static readonly Phrase SavedListAria =
        new("Postările salvate", "The saved posts");
    public static readonly Phrase UnsavedDraft = new(
        "Ciornă nesalvată. Postarea din bibliotecă rămâne neschimbată până confirmi.",
        "Unsaved draft. The stored post stays unchanged until you confirm.");
    public static readonly Phrase HashtagsHint = new(
        "(3–5, separate prin spațiu)", "(3–5, separated by spaces)");
    public static readonly Phrase LegacyProductionNote = new(
        "Postarea aceasta e dinainte de blocul de producție. Completează cele trei câmpuri o singură dată ca să o poți salva mai departe.",
        "This post predates the production block. Fill the three fields once so you can keep saving it.");
    public static readonly Phrase FieldDuration =
        new("Durată sau număr de cadre", "Duration or number of frames");
    public static readonly Phrase FieldVisual = new("Direcție vizuală", "Visual direction");
    public static readonly Phrase FieldBlocks = new("Blocuri de conținut", "Content blocks");
    public static readonly Phrase BlocksHint = new("(unul pe linie)", "(one per line)");
    public static readonly Phrase DiscardChanges =
        new("Renunță la modificări", "Discard changes");
    public static readonly Phrase SaveChanges = new("Salvează modificările", "Save changes");
    public static readonly Phrase ReplacePostTitle =
        new("Înlocuiești postarea salvată?", "Replace the saved post?");
    public static readonly Phrase ReplacePostMessage = new(
        "Versiunea de acum se pierde definitiv; nu există istoric. Confirmă doar dacă textul de mai sus e cel bun.",
        "The current version is lost for good; there is no history. Confirm only if the text above is the right one.");
    public static readonly Phrase PostReplaced =
        new("Postarea a fost înlocuită.", "The post was replaced.");
    public static readonly Phrase ChangeCancelled = new(
        "Modificarea a fost anulată. Postarea a rămas cum era.",
        "The change was cancelled. The post stayed as it was.");

    // ---- profile page -------------------------------------------------------
    public static readonly Phrase ProfileTab =
        new("Profil · Studio Viorela", "Profile · Studio Viorela");
    public static readonly Phrase ProfileEyebrow = new(
        "Vocea din spatele conținutului", "The voice behind the content");
    public static readonly Phrase ProfileLede = new(
        "Agentul folosește aceste informații în fiecare idee. Editează doar ce s-a schimbat și confirmă înainte de salvare.",
        "The agent uses this in every idea. Edit only what changed, and confirm before it is saved.");
    public static readonly Phrase ProfileHeading =
        new("Profilul brandului", "The brand profile");
    public static readonly Phrase ProfileChip = new("Sursă vie · MCP", "Live source · MCP");
    public static readonly Phrase SaveNeedsConfirm = new(
        "Salvarea cere confirmarea ta.", "Saving needs your confirmation.");
    public static readonly Phrase ProfileLoading =
        new("Se încarcă profilul actual…", "Loading the current profile…");
    public static readonly Phrase ProfileFailed =
        new("Profilul nu a putut fi încărcat.", "The profile could not be loaded.");
    public static readonly Phrase FromMethod = new("din metodă", "from the method");
    public static readonly Phrase PrepareSaveShort =
        new("Pregătește salvarea", "Prepare the save");
    public static readonly Phrase ChangeSaved =
        new("Modificarea a fost salvată.", "The change was saved.");
    public static readonly Phrase ChangeCancelledShort =
        new("Modificarea a fost anulată.", "The change was cancelled.");

    // ---- materials page -----------------------------------------------------
    public static readonly Phrase LibraryTab =
        new("Materiale · Studio Viorela", "Materials · Studio Viorela");
    public static readonly Phrase LibraryEyebrow =
        new("Sursa de inspirație", "The source of inspiration");
    public static readonly Phrase LibraryHeading = new("Materialele tale", "Your materials");
    public static readonly Phrase LibraryLede = new(
        "Cărțile, notițele și documentele încărcate vor alimenta ideile fără să schimbe vocea brandului.",
        "Uploaded books, notes and documents will feed the ideas without changing the brand voice.");
    public static readonly Phrase LibraryAdd = new("＋ Adaugă material", "＋ Add material");
    public static readonly Phrase LibraryComingHeading = new(
        "Biblioteca se conectează în etapa media",
        "The library gets connected in the media stage");
    public static readonly Phrase LibraryComingBody = new(
        "Atunci vom adăuga încărcare, procesare și embeddings automate, cu stare vizibilă pentru fiecare fișier.",
        "That is when upload, processing and automatic embeddings arrive, with a visible state per file.");

    // ---- chat drawer --------------------------------------------------------
    public static readonly Phrase ChatLauncher =
        new("Vorbește cu agentul", "Talk to the agent");
    public static readonly Phrase ChatEyebrow = new("Asistentul tău", "Your assistant");
    public static readonly Phrase ChatAria = new("Chat cu agentul", "Chat with the agent");
    public static readonly Phrase ChatContext = new("Context", "Context");
    public static readonly Phrase ChatGeneral =
        new("Conversație generală", "General conversation");
    public static readonly Phrase ChatSavedPrefix = new("Salvată", "Saved");
    public static readonly Phrase ChatYou = new("Tu", "You");
    public static readonly Phrase ChatAgent = new("Agent", "Agent");
    public static readonly Phrase ChatMicrophone =
        new("Microfon — etapa media", "Microphone — media stage");
    public static readonly Phrase ChatSend = new("Trimite", "Send");
    public static readonly Phrase ChatHeading =
        new("Hai să lucrăm împreună", "Let us work together");
    public static readonly Phrase ChatClose = new("Închide chatul", "Close the chat");
    public static readonly Phrase ChatEmptyTitle = new(
        "Spune-i ce vrei să schimbi.", "Tell it what you want to change.");
    public static readonly Phrase ChatEmptyBody = new(
        "Dacă ai deschis o variantă, agentul lucrează exact pe ea. Altfel răspunde în conversația generală.",
        "If you have a variant open, the agent works on exactly that one. Otherwise it answers in the general conversation.");
    public static readonly Phrase ChatStreaming = new("Răspuns în curs", "Answer in progress");
    public static readonly Phrase ChatStopped = new(
        "Răspuns oprit · textul parțial nu a modificat conținutul.",
        "Answer stopped · the partial text changed no content.");
    public static readonly Phrase ChatPostRewritten = new(
        "✎ Postarea a fost rescrisă în editor. Se salvează abia după «Salvează modificările».",
        "✎ The post was rewritten in the editor. It is saved only after “Save changes”.");
    public static readonly Phrase ChatVariantUpdated = new(
        "✓ Varianta din generator a fost actualizată.",
        "✓ The variant in the generator was updated.");
    public static readonly Phrase ChatPlaceholder = new(
        "Scrie-i agentului în limba română…", "Write to the agent in English…");
    public static readonly Phrase ChatAttachments =
        new("Atașamente — etapa media", "Attachments — media stage");
    public static readonly Phrase ChatStopping =
        new("Se oprește răspunsul…", "Stopping the answer…");
    public static readonly Phrase ChatNeedsApproval = new(
        "Agentul a pregătit o scriere care are nevoie de confirmare. Salvarea se face din pagina ei, cu butonul de salvare.",
        "The agent prepared a write that needs confirmation. Save it from its own page, with the save button.");
    public static readonly Phrase ChatUnfinished = new(
        "Răspunsul nu a putut fi terminat.", "The answer could not be finished.");
    public static readonly Phrase ChatReconnecting = new(
        "Conexiunea live se reface automat; răspunsul continuă pe server.",
        "The live connection restores itself; the answer continues on the server.");
    public static readonly Phrase ChatNewConversation =
        new("Conversație nouă", "New conversation");
    public static readonly Phrase ChatNewConversationHint = new(
        "Începe o conversație nouă; lotul curent iese din interfață.",
        "Start a fresh conversation; the current batch leaves the interface.");
    public static readonly Phrase ChatHistoryError = new(
        "Conversația nu a putut fi încărcată.", "The conversation could not be loaded.");
    public static readonly Phrase ChatToolRow =
        new("unealtă", "tool");

    // ---- not found ----------------------------------------------------------
    public static readonly Phrase NotFoundTab = new("Pagină negăsită", "Page not found");
    public static readonly Phrase NotFoundHeading =
        new("Pagina aceasta nu există", "This page does not exist");
    public static readonly Phrase NotFoundBody = new(
        "Întoarce-te la generator și continuă de acolo.",
        "Go back to the generator and carry on from there.");
    public static readonly Phrase NotFoundCta =
        new("Deschide generatorul", "Open the generator");

    // ---- Budget and accounts -------------------------------------------------
    // Nothing in this block names a sum, a token count or a model. A tester sees
    // how much of their allowance is left, never what anything cost.
    public static readonly Phrase UsageLabel = new("Consum", "Usage");
    public static readonly Phrase UsageRemaining =
        new("{0}% folosit", "{0}% used");
    public static readonly Phrase BudgetExhausted = new(
        "Ai atins limita contului. Cere-i lui Sorin să o ridice ca să continui.",
        "You have reached this account's limit. Ask Sorin to raise it to carry on.");

    // Not the same sentence as the budget: this one passes on its own, and
    // saying "limit" for both would teach the reader that the two are one thing.
    public static readonly Phrase RateLimited = new(
        "Prea multe cereri într-un minut. Așteaptă puțin și încearcă din nou.",
        "Too many requests in one minute. Wait a moment and try again.");

    // An empty shelf is a legitimate state - a new account starts with one -
    // so this explains rather than apologises, and names the way out.
    public static readonly Phrase LibraryEmptyForBooks = new(
        "Nu ai încă materiale în bibliotecă, deci sursa „Cărți” nu are unde căuta. "
        + "Alege „Memorie” sau „Internet”, sau adaugă întâi materiale.",
        "You have no materials in your library yet, so the “Books” source has "
        + "nowhere to look. Choose “Memory” or “Internet”, or add materials first.");
    public static readonly Phrase LibraryEmptyForMixed = new(
        "Biblioteca ta e goală, deci „Combinat” va folosi doar memoria și internetul.",
        "Your library is empty, so “Mixed” will use only memory and the internet.");

    public static readonly Phrase AccountNotProvisioned = new(
        "Contul tău nu are încă un spațiu de lucru. Cere-i lui Sorin să ți-l creeze.",
        "Your account does not have a workspace yet. Ask Sorin to create one.");

    public static readonly Phrase ProfileSectionUnknown = new(
        "Secțiunea de profil nu există sau nu poate fi editată.",
        "That profile section does not exist, or cannot be edited.");
    public static readonly Phrase ProfileSectionEmpty = new(
        "Secțiunea nu poate rămâne goală.",
        "The section cannot be left empty.");
    public static readonly Phrase PostNotFound = new(
        "Postarea salvată nu mai există.",
        "That saved post no longer exists.");
    public static readonly Phrase NoCurrentBatch = new(
        "Nu există un lot curent din care să salvezi.",
        "There is no current batch to save from.");

    public static readonly Phrase AdminCannotSuspendSelf = new(
        "Nu îți poți suspenda propriul cont.",
        "You cannot suspend your own account.");
    public static readonly Phrase AdminCannotSuspendAdmin = new(
        "Un administrator nu poate fi suspendat de aici.",
        "An administrator cannot be suspended from here.");
    public static readonly Phrase AdminAccountMissing = new(
        "Contul nu există.",
        "That account does not exist.");

    public static readonly Phrase AdminNoSignIn = new(
        "nimeni nu s-a autentificat încă",
        "nobody has signed in yet");

    public static readonly Phrase AdminSuspend = new("Suspendă", "Suspend");
    public static readonly Phrase AdminRestore = new("Reactivează", "Restore");
    public static readonly Phrase AdminSuspended = new("suspendat", "suspended");
    public static readonly Phrase AdminSuspendSaved = new(
        "Accesul contului a fost schimbat.",
        "The account's access has been changed.");

    public static readonly Phrase AdminNav = new("Administrare", "Admin");
    public static readonly Phrase AdminTitle = new("Conturi de test", "Test accounts");
    public static readonly Phrase AdminIntro = new(
        "Conturile noi se creează în tenant, nu aici. Limita e pe viață, nu lunară.",
        "New accounts are created in the tenant, not here. The limit is for life, not monthly.");
    public static readonly Phrase AdminColAccount = new("Cont", "Account");
    public static readonly Phrase AdminColRole = new("Rol", "Role");
    public static readonly Phrase AdminColUsed = new("Folosit", "Used");
    public static readonly Phrase AdminColBudget = new("Limită", "Limit");
    public static readonly Phrase AdminColCalls = new("Apeluri", "Calls");
    public static readonly Phrase AdminColLastUsed = new("Ultima dată", "Last used");
    public static readonly Phrase AdminNever = new("niciodată", "never");
    public static readonly Phrase AdminSetBudget = new("Schimbă limita", "Change limit");
    public static readonly Phrase AdminSave = new("Salvează", "Save");
    public static readonly Phrase AdminCancel = new("Renunță", "Cancel");
    public static readonly Phrase AdminEmpty = new(
        "Niciun cont provizionat încă. Primul admin se face din terminal.",
        "No accounts provisioned yet. The first admin is made from the terminal.");
    public static readonly Phrase AdminForbidden = new(
        "Pagina aceasta este numai pentru administrator.",
        "This page is for the administrator only.");
    public static readonly Phrase AdminBudgetSaved = new("Limită salvată.", "Limit saved.");
}
