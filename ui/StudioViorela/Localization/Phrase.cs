namespace StudioViorela.Localization;

/// <summary>
/// One piece of interface text in both languages, on one line.
///
/// The alternative — two dictionaries, or two objects with the same property
/// names — lets a translation drift the moment somebody edits one side and not
/// the other, and nothing complains. Keeping the pair together makes the drift
/// impossible to miss in a diff, which is the whole reason for the shape.
/// </summary>
public sealed class Phrase(string ro, string en)
{
    public string Ro { get; } = ro;
    public string En { get; } = en;
}

/// <summary>
/// Resolves phrases into the language currently on screen.
///
/// Cascaded from <c>MainLayout</c> so that switching the language re-renders
/// every descendant without a single page having to subscribe to anything.
/// </summary>
public sealed class Translator(string code)
{
    /// <summary>"ro" or "en" — also what the API is told on every request.</summary>
    public string Code { get; } = code;

    public bool IsEnglish => Code == "en";

    public string this[Phrase phrase] => IsEnglish ? phrase.En : phrase.Ro;

    /// <summary>Picks between two ready strings, for the rare inline case.</summary>
    public string Pick(string ro, string en) => IsEnglish ? en : ro;
}
