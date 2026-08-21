using Microsoft.JSInterop;
using StudioViorela.Localization;

namespace StudioViorela.Services;

/// <summary>
/// Which language the studio is being used in, for this browser.
///
/// It is deliberately *not* seeded from `navigator.language`. The client works
/// in Romanian, and a Romanian speaker running an English Windows would open the
/// studio in a language she did not ask for. So Romanian is the default until
/// somebody picks otherwise, and the pick is remembered.
///
/// Every read and write of local storage is wrapped: a browser with site data
/// blocked throws on access, and that must cost the visitor a preference, not
/// the application.
/// </summary>
public sealed class LanguageState(IJSRuntime js)
{
    private const string StorageKey = "studio-viorela-language";

    public string Code { get; private set; } = "ro";

    public Translator Translator { get; private set; } = new("ro");

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
            // accessor outright. Romanian it is.
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
