using Microsoft.JSInterop;
using StudioViorela.Localization;

namespace StudioViorela.Services;

/// <summary>
/// Which language the studio is being used in, for this browser.
///
/// It is deliberately *not* seeded from `navigator.language`. A browser locale
/// is a guess about the reader, and a wrong guess opens the studio in a language
/// nobody asked for - in either direction. So there is one fixed starting
/// language, and the pick that overrides it is remembered.
///
/// That starting language is English since 2026-08-31, and it is a decision
/// rather than a default: the studio is shown to people who do not read
/// Romanian, and a visitor arrives with nothing stored. The asymmetry is what
/// makes it safe - a visitor who has never picked is a stranger, and the client
/// is not: she picks Romanian once and the stored value wins on every later
/// visit. The one cost is her next visit after this deploy, which opens in
/// English until she clicks.
///
/// The server's own DEFAULT_LANGUAGE stays Romanian, and that is not an
/// inconsistency: it answers a different question - what a request that names
/// NO language falls back to - and every request from this client names one.
///
/// Every read and write of local storage is wrapped: a browser with site data
/// blocked throws on access, and that must cost the visitor a preference, not
/// the application.
/// </summary>
public sealed class LanguageState(IJSRuntime js)
{
    private const string StorageKey = "studio-viorela-language";

    public string Code { get; private set; } = "en";

    public Translator Translator { get; private set; } = new("en");

    /// <summary>Raised after the language changes, so the shell can re-render.</summary>
    public event Action? Changed;

    public async Task InitializeAsync()
    {
        string? stored = null;
        try
        {
            stored = await js.InvokeAsync<string?>("localStorage.getItem", StorageKey);
        }
        catch (Exception)
        {
            // Private window, blocked site data, or a host that denies the
            // accessor outright. The starting language it is.
        }

        if (stored is "ro" or "en" && stored != Code)
        {
            Apply(stored);
        }
    }

    public async Task SetAsync(string code)
    {
        if (code is not ("ro" or "en") || code == Code)
        {
            return;
        }

        Apply(code);
        try
        {
            await js.InvokeVoidAsync("localStorage.setItem", StorageKey, code);
        }
        catch (Exception)
        {
            // The switch still took effect for this visit; it just will not
            // survive a reload. Better than failing the click.
        }
    }

    private void Apply(string code)
    {
        Code = code;
        Translator = new Translator(code);
        Changed?.Invoke();
    }
}
