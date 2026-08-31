namespace StudioViorela;

/// <summary>
/// Romanian agreement for counted nouns. Everything the client reads is
/// Romanian, and "1 postări" reads as a machine talking, not her studio.
/// </summary>
public static class RomanianText
{
    /// <summary>
    /// Romanian takes "de" before the noun from twenty upwards, except when the
    /// last two digits fall between 01 and 19: 20 de postări, but 101 postări.
    /// </summary>
    public static bool NeedsDe(int count)
    {
        var tail = Math.Abs(count) % 100;
        return Math.Abs(count) >= 20 && (tail == 0 || tail >= 20);
    }

    /// <summary>Formats a count with its noun, e.g. "o postare", "3 postări", "20 de postări".</summary>
    public static string Count(int count, string singular, string plural, string? one = null)
    {
        if (count == 1)
        {
            return one ?? $"1 {singular}";
        }

        return NeedsDe(count) ? $"{count} de {plural}" : $"{count} {plural}";
    }

    /// <summary>"o postare salvată" / "4 postări salvate" — the past participle agrees too.</summary>
    public static string SavedPosts(int count) =>
        Count(count, "postare salvată", "postări salvate", one: "o postare salvată");

    public static string Posts(int count) =>
        Count(count, "postare", "postări", one: "o postare");

    /// <summary>"un material" / "17 materiale" / "20 de materiale".</summary>
    public static string Materials(int count) =>
        Count(count, "material", "materiale", one: "un material");
}
