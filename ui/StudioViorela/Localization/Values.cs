namespace StudioViorela.Localization;

/// <summary>
/// Domain vocabulary: the label translates, the value never does.
///
/// A pillar, a source, a format and a hook type are part of the API contract —
/// `GenerationStartRequest` validates them, the MCP tools store them, and the
/// skills reason about them by their Romanian names. Translating a value would
/// break the request; translating the label is the whole point of a language
/// switch. So every helper here maps a stable Romanian value to a label, and
/// nothing writes in the other direction.
/// </summary>
public static class Values
{
    /// <summary>Source values, in the order the picker shows them.</summary>
    public static readonly string[] Sources = ["Memorie", "Cărți", "Internet", "Combinat"];

    public static string SourceLabel(Translator t, string value) => value switch
    {
        "Memorie" => t.Pick("Memorie", "Memory"),
        "Cărți" => t.Pick("Cărți", "Books"),
        "Internet" => t.Pick("Internet", "Internet"),
        "Combinat" => t.Pick("Combinat", "Mixed"),
        _ => value
    };

    public static readonly string[] Pillars =
        ["Poziționare", "Educație", "Conexiune", "Conversie", "Magnetism"];

    public static string PillarLabel(Translator t, string value) => value switch
    {
        "Poziționare" => t.Pick("Poziționare", "Positioning"),
        "Educație" => t.Pick("Educație", "Education"),
        "Conexiune" => t.Pick("Conexiune", "Connection"),
        "Conversie" => t.Pick("Conversie", "Conversion"),
        "Magnetism" => t.Pick("Magnetism", "Magnetism"),
        _ => value
    };

    // There is no model picker here since 2026-08-27: nano was removed after it
    // failed to drive the sandbox shell, and a select with one option is a
    // control that promises a choice it cannot give. The server picks.
    //
    // If a second model ever earns its place, the rule that governed the labels
    // comes back with it: they say how carefully the thing is written, never
    // what it costs. The studio shows a tester a percentage of their allowance
    // and never a figure, and a picker reading "cheap / expensive" would undo
    // that in one glance.

    public static readonly string[] Formats = ["Reel", "Carusel", "Stories"];

    public static string FormatLabel(Translator t, string value) => value switch
    {
        "Reel" => t.Pick("Reel", "Reel"),
        "Carusel" => t.Pick("Carusel", "Carousel"),
        "Stories" => t.Pick("Stories", "Stories"),
        _ => value
    };

    /// <summary>The five hook types, stored upper-case without diacritics.</summary>
    public static string HookLabel(Translator t, string value) => value switch
    {
        "PROVOCARE" => t.Pick("Provocare", "Challenge"),
        "CIFRA" => t.Pick("Cifră", "Number"),
        "SECRET" => t.Pick("Secret", "Secret"),
        "INTREBARE" => t.Pick("Întrebare", "Question"),
        "CONTRAST" => t.Pick("Contrast", "Contrast"),
        _ => value
    };

    // ---- live status text ---------------------------------------------------

    public static string IdeaStatus(Translator t, string status, int retryCount) =>
        status switch
        {
            "waiting" => t.Pick("așteaptă detaliile", "waiting for details"),
            "generating" => t.Pick("se dezvoltă acum", "developing now"),
            "retrying" => t.Pick(
                $"se reîncearcă · încercarea {retryCount + 1}",
                $"retrying · attempt {retryCount + 1}"),
            "ready" => t.Pick("5 variante gata", "5 variants ready"),
            "failed" => t.Pick("nefinalizată", "unfinished"),
            "cancelled" => t.Pick("oprită", "stopped"),
            _ => status
        };

    public static string BatchStatus(
        Translator t, string status, int readyIdeas, int titles) =>
        status switch
        {
            "gathering" => t.Pick(
                "Se generează cele 10 titluri. Poți lăsa pagina deschisă.",
                "The 10 titles are being generated. You can leave the page open."),
            // Said "pornesc detaliile" until 2026-08-24, and from that day it
            // was a lie: the batch writes titles and stops. She opens the ones
            // she wants. A status line that promises work nobody is doing is
            // the same fault as one that contradicts the cards under it.
            "titles_ready" when readyIdeas == 0 => t.Pick(
                "Cele 10 titluri sunt gata. Deschide-le pe cele care îți plac și "
                    + "ți le scriu întregi.",
                "The 10 titles are ready. Open the ones you like and I will write "
                    + "them in full."),
            "titles_ready" => t.Pick(
                $"{readyIdeas} din 10 dezvoltate. Deschide oricare alta ca s-o scriu.",
                $"{readyIdeas} of 10 developed. Open any other one and I will write it."),
            "generating" => t.Pick(
                $"{readyIdeas}/10 idei dezvoltate complet.",
                $"{readyIdeas}/10 ideas fully developed."),
            // `readyIdeas` was passed in and ignored here until 2026-08-24, so a
            // batch that finished with failures still announced all ten as
            // complete. Seen twice in one afternoon: idea 5 lost to a rate limit,
            // idea 9 to a malformed structured output, and both times this line
            // said everything was fine while the card underneath read
            // "nefinalizată". A status line that contradicts the thing it is
            // describing is worse than no status line.
            "ready" when readyIdeas >= 10 => t.Pick(
                "Toate cele 10 idei au câte 5 variante complete.",
                "All 10 ideas have 5 complete variants each."),
            // Said "restul nu au ieșit" until 2026-08-24, which stopped being
            // true the day details became something she asks for: the rest were
            // never attempted. Blaming a failure that did not happen teaches her
            // to distrust the ones that did.
            "ready" => t.Pick(
                $"{readyIdeas} din 10 idei sunt scrise întreg. "
                    + "Deschide oricare alta ca s-o scriu și pe ea.",
                $"{readyIdeas} of 10 ideas are written in full. "
                    + "Open any other one and I will write that too."),
            // A batch that never produced a title has no "ideas that were
            // ready", and saying so above an empty list is the same fault as
            // the two above: a status line contradicting what is under it.
            "failed" when titles == 0 => t.Pick(
                "Lotul s-a oprit fără să scrie ceva.",
                "The batch stopped without writing anything."),
            "failed" => t.Pick(
                "Lotul s-a oprit; ideile gata au rămas disponibile.",
                "The batch stopped; the ideas that were ready are still available."),
            "cancelled" when titles == 0 => t.Pick(
                "Lotul a fost oprit înainte de primul titlu.",
                "The batch was stopped before the first title."),
            "cancelled" => t.Pick("Lotul a fost oprit.", "The batch was stopped."),
            "replaced" => t.Pick("Lotul a fost înlocuit.", "The batch was replaced."),
            _ => status
        };

    /// <summary>
    /// What she reads when one idea fails.
    ///
    /// The harness stores a CODE in `generation_ideas.last_error`, not a
    /// sentence, because the card prints that column verbatim — it is the one
    /// client-facing string with no language net in front of it, and a row
    /// written in Romanian in March is still Romanian when an English page
    /// reads it in June.
    ///
    /// An unrecognised value passes straight through. That is deliberate: rows
    /// written before 2026-08-31 hold whole Romanian sentences, and showing her
    /// the sentence she already saw beats showing her nothing. It is also the
    /// one way this can fail quietly — see the test in
    /// `tests/unit/test_failure_diagnosis.py` that reads this file.
    /// </summary>
    /// <summary>One errand of a run, in the reader's language.</summary>
    /// <remarks>
    /// An unknown code falls back to the generic word rather than printing
    /// itself: this is decoration on a working page, and a raw `exec_command`
    /// in the middle of her chat would be worse than a vague one.
    /// </remarks>
    public static string ActivityLabel(Translator t, string? code) => code switch
    {
        "books" => t[Copy.ActivityBooks],
        "web" => t[Copy.ActivityWeb],
        "method" => t[Copy.ActivityMethod],
        _ => t[Copy.ActivityTool]
    };

    public static string GenerationError(Translator t, string? code)
    {
        if (string.IsNullOrWhiteSpace(code))
        {
            return string.Empty;
        }
        if (code.StartsWith("failed:", StringComparison.Ordinal))
        {
            var name = code["failed:".Length..];
            return t.Pick(
                $"Generarea a eșuat ({name}).", $"The generation failed ({name}).");
        }
        return code switch
        {
            "rate_limit" => t.Pick(
                "Limita temporară a modelului a fost atinsă.",
                "The model's temporary rate limit was reached."),
            "structured_output" => t.Pick(
                "Modelul nu a respectat formatul structurat.",
                "The model did not honour the structured format."),
            "max_turns" => t.Pick(
                "Skill-ul nu a terminat în limita de pași.",
                "The skill did not finish within its step limit."),
            "timeout" => t.Pick(
                "Generarea a depășit timpul maxim.",
                "The generation ran past its time limit."),
            "missing_config" => t.Pick(
                "Studioul nu e configurat complet; generarea nu poate porni.",
                "The studio is not fully configured; generation cannot start."),
            _ => code,
        };
    }

    // ---- profile sections ---------------------------------------------------

    public static string GroupLabel(Translator t, string group) => group switch
    {
        "identity" => t.Pick("Identitate", "Identity"),
        "ideal_client" => t.Pick("Client ideal", "Ideal client"),
        "voice" => t.Pick("Voce și ton", "Voice and tone"),
        "offer" => t.Pick("Ofertă", "Offer"),
        "pillars" => t.Pick("Piloni", "Pillars"),
        "ctas" => t.Pick("Îndemnuri", "Calls to action"),
        "restrictions" => t.Pick("Limite", "Limits"),
        "results" => t.Pick("Rezultate", "Results"),
        _ => t.Pick("Profil", "Profile")
    };

    public static string BlockLabel(Translator t, string kind) => kind switch
    {
        "bullet" => t.Pick("Punct", "Point"),
        "ordered" => t.Pick("Pas", "Step"),
        "quote" => t.Pick("Formulare exactă", "Exact wording"),
        _ => t.Pick("Descriere", "Description")
    };

    // ---- counted nouns ------------------------------------------------------

    /// <summary>
    /// "o postare" / "3 postări" / "20 de postări", or the plain English plural.
    /// Romanian agreement is not a formatting detail — "1 postări" reads as a
    /// machine talking, which is why <see cref="RomanianText"/> exists at all.
    /// </summary>
    public static string Posts(Translator t, int count) => t.IsEnglish
        ? count == 1 ? "1 post" : $"{count} posts"
        : RomanianText.Posts(count);

    public static string SavedPosts(Translator t, int count) => t.IsEnglish
        ? count == 1 ? "1 saved post" : $"{count} saved posts"
        : RomanianText.SavedPosts(count);

    public static string Materials(Translator t, int count) => t.IsEnglish
        ? count == 1 ? "1 material" : $"{count} materials"
        : RomanianText.Materials(count);
}
