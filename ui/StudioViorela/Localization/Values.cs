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

    public static string BatchStatus(Translator t, string status, int readyIdeas) =>
        status switch
        {
            "gathering" => t.Pick(
                "Se generează cele 10 titluri. Poți lăsa pagina deschisă.",
                "The 10 titles are being generated. You can leave the page open."),
            "titles_ready" => t.Pick(
                "Titlurile sunt gata; pornesc detaliile.",
                "The titles are ready; the details are starting."),
            "generating" => t.Pick(
                $"{readyIdeas}/10 idei dezvoltate complet.",
                $"{readyIdeas}/10 ideas fully developed."),
            "ready" => t.Pick(
                "Toate cele 10 idei au câte 5 variante complete.",
                "All 10 ideas have 5 complete variants each."),
            "failed" => t.Pick(
                "Lotul s-a oprit; ideile gata au rămas disponibile.",
                "The batch stopped; the ideas that were ready are still available."),
            "cancelled" => t.Pick("Lotul a fost oprit.", "The batch was stopped."),
            "replaced" => t.Pick("Lotul a fost înlocuit.", "The batch was replaced."),
            _ => status
        };

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
}
