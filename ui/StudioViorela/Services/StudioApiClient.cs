using System.Net.Http.Json;
using System.Text.Json;
using StudioViorela.Localization;
using StudioViorela.Models;

namespace StudioViorela.Services;

// The language is stamped here rather than at each call site: a page that
// forgets it would quietly get Romanian back while showing English, and
// nothing would fail loudly enough to notice.
public sealed class StudioApiClient(HttpClient http, LanguageState language)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    // Named Tr, not T: the generic parameter of ReadAsync<T> already owns T.
    private Translator Tr => language.Translator;

    public Task<AuthOptionsDto> GetAuthOptionsAsync() =>
        GetAsync<AuthOptionsDto>("api/auth/options");

    public Task<MeDto> GetMeAsync() => GetAsync<MeDto>("api/me");

    public Task<UsageDto> GetUsageAsync() => GetAsync<UsageDto>("api/me/usage");

    public Task<AdminAccountsDto> GetAdminAccountsAsync() =>
        GetAsync<AdminAccountsDto>("api/admin/accounts");

    public async Task SetDisabledAsync(string principalId, bool disabled)
    {
        using var response = await http.PutAsJsonAsync(
            $"api/admin/accounts/{Uri.EscapeDataString(principalId)}/disabled",
            new SetDisabledDto { Disabled = disabled },
            Json);
        await EnsureSuccessAsync(response);
    }

    public async Task SetBudgetAsync(string clientSlug, long budgetMicros)
    {
        using var response = await http.PutAsJsonAsync(
            $"api/admin/accounts/{Uri.EscapeDataString(clientSlug)}/budget",
            new SetBudgetDto { BudgetMicros = budgetMicros },
            Json);
        await EnsureSuccessAsync(response);
    }

    public Task<ProfileSectionsDto> GetProfileAsync() =>
        GetAsync<ProfileSectionsDto>("api/profile/sections");

    public Task<RunResponseDto> PrepareProfileUpdateAsync(ProfileSectionDto section) =>
        PostAsync<ProfileUpdateDto, RunResponseDto>(
            $"api/profile/sections/{Uri.EscapeDataString(section.Key)}/runs",
            new ProfileUpdateDto { Blocks = section.Blocks });

    public Task<RunResponseDto> DecideAsync(RunResponseDto run, bool approved) =>
        PostAsync<DecisionsDto, RunResponseDto>(
            $"api/runs/{Uri.EscapeDataString(run.RunId)}/decisions",
            new DecisionsDto
            {
                SessionId = run.SessionId,
                Decisions = run.Requests.Select(request => new DecisionDto
                {
                    CallId = request.CallId,
                    Approved = approved,
                    Reason = approved ? "Confirmat din interfața Studio." : "Anulat din interfața Studio."
                }).ToList(),
                Language = language.Code
            });

    public Task<SavedPostsResponseDto> GetSavedPostsAsync() =>
        GetAsync<SavedPostsResponseDto>("api/posts");

    public Task<SavedPostEnvelopeDto> GetSavedPostAsync(string postId) =>
        GetAsync<SavedPostEnvelopeDto>($"api/posts/{Uri.EscapeDataString(postId)}");

    public Task<RunResponseDto> PrepareBatchSaveAsync(IEnumerable<string> variantIds) =>
        PostAsync<SavePostsRequestDto, RunResponseDto>(
            "api/posts/save-runs",
            new SavePostsRequestDto { VariantIds = variantIds.ToList() });

    public Task<RunResponseDto> PreparePostUpdateAsync(
        string postId, PostContentDto content) =>
        PostAsync<PostContentDto, RunResponseDto>(
            $"api/posts/{Uri.EscapeDataString(postId)}/runs", content);

    public Task<LibraryResponseDto> GetLibraryAsync() =>
        GetAsync<LibraryResponseDto>("api/library");

    public Task<GenerationBatchEnvelopeDto> GetCurrentGenerationAsync() =>
        GetAsync<GenerationBatchEnvelopeDto>("api/generation-batches/current");

    public Task<GenerationBatchEnvelopeDto> GetGenerationAsync(string batchId) =>
        GetAsync<GenerationBatchEnvelopeDto>(
            $"api/generation-batches/{Uri.EscapeDataString(batchId)}");

    public Task<GenerationBatchEnvelopeDto> StartGenerationAsync(
        GenerationStartDto request)
    {
        request.Language = language.Code;
        return PostAsync<GenerationStartDto, GenerationBatchEnvelopeDto>(
            "api/generation-batches", request);
    }

    public async Task CancelGenerationAsync(string batchId)
    {
        using var response = await http.PostAsync(
            $"api/generation-batches/{Uri.EscapeDataString(batchId)}/cancel", null);
        await EnsureSuccessAsync(response);
    }

    public async Task SelectVariantAsync(string variantId)
    {
        using var response = await http.PutAsJsonAsync(
            $"api/generation-variants/{Uri.EscapeDataString(variantId)}/selection",
            new VariantSelectionDto(),
            Json);
        await EnsureSuccessAsync(response);
    }

    public string GenerationEventsUrl(string batchId) =>
        new Uri(
            http.BaseAddress!,
            $"api/generation-batches/{Uri.EscapeDataString(batchId)}/events")
        .ToString();

    public Task<ChatAcceptedDto> StartChatAsync(ChatStartDto request)
    {
        request.Language = language.Code;
        return PostAsync<ChatStartDto, ChatAcceptedDto>("api/chat/runs", request);
    }

    public async Task CancelChatAsync(string runId)
    {
        using var response = await http.PostAsync(
            $"api/runs/{Uri.EscapeDataString(runId)}/cancel", null);
        await EnsureSuccessAsync(response);
    }

    public string ChatEventsUrl(string runId) =>
        new Uri(
            http.BaseAddress!,
            $"api/runs/{Uri.EscapeDataString(runId)}/events")
        .ToString();

    private async Task<T> GetAsync<T>(string path)
    {
        using var response = await http.GetAsync(path);
        return await ReadAsync<T>(response);
    }

    private async Task<TResponse> PostAsync<TRequest, TResponse>(string path, TRequest body)
    {
        using var response = await http.PostAsJsonAsync(path, body, Json);
        return await ReadAsync<TResponse>(response);
    }

    private async Task<T> ReadAsync<T>(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode)
        {
            var detail = await ReadErrorAsync(response);
            throw new StudioApiException((int)response.StatusCode, detail);
        }

        return await response.Content.ReadFromJsonAsync<T>(Json)
            ?? throw new InvalidOperationException(Tr[Copy.EmptyResponse]);
    }

    private async Task EnsureSuccessAsync(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode)
        {
            throw new StudioApiException(
                (int)response.StatusCode, await ReadErrorAsync(response));
        }
    }

    /// <summary>
    /// Romanian diacritics are the cheap, reliable tell. A Romanian sentence
    /// without one of these reads as neutral enough to pass, which is the right
    /// failure direction: the net catches what would look obviously wrong.
    /// </summary>
    private static bool IsRomanian(string text) =>
        text.IndexOfAny(new[] { 'ă', 'â', 'î', 'ș', 'ț', 'Ă', 'Â', 'Î', 'Ș', 'Ț' }) >= 0;

    private async Task<string> ReadErrorAsync(HttpResponseMessage response)
    {
        try
        {
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());

            // The server sends a code rather than a sentence when a run is
            // refused for money, so that the wording is chosen here, in the
            // reader's language - and so that it never names a sum.
            if (document.RootElement.TryGetProperty("code", out var code))
            {
                switch (code.GetString())
                {
                    case "budget_exhausted":
                        return Tr[Copy.BudgetExhausted];
                    case "rate_limited":
                        return Tr[Copy.RateLimited];
                    case "cannot_suspend_self":
                        return Tr[Copy.AdminCannotSuspendSelf];
                    case "cannot_suspend_admin":
                        return Tr[Copy.AdminCannotSuspendAdmin];
                    case "account_not_found":
                        return Tr[Copy.AdminAccountMissing];
                    case "profile_section_unknown":
                        return Tr[Copy.ProfileSectionUnknown];
                    case "profile_section_empty":
                        return Tr[Copy.ProfileSectionEmpty];
                    case "post_not_found":
                        return Tr[Copy.PostNotFound];
                    case "no_current_batch":
                        return Tr[Copy.NoCurrentBatch];
                    case "account_not_provisioned":
                        return Tr[Copy.AccountNotProvisioned];
                }
            }

            if (document.RootElement.TryGetProperty("detail", out var detail))
            {
                if (detail.ValueKind == JsonValueKind.String)
                {
                    // The safety net, and the reason it is here rather than in
                    // each call site: most of the harness's refusals are written
                    // in Romanian, because Romanian is the language the studio is
                    // run in. Passed through verbatim, one of them would appear
                    // mid-sentence on an English page - which is precisely what
                    // the language switch exists to prevent. A refusal worth
                    // wording exactly gets a `code` above; everything else says
                    // so generically rather than saying it in the wrong language.
                    var sentence = detail.GetString();
                    if (string.IsNullOrWhiteSpace(sentence))
                    {
                        return Tr[Copy.RequestFailed];
                    }
                    return Tr.IsEnglish && IsRomanian(sentence)
                        ? Tr[Copy.RequestFailed]
                        : sentence;
                }
                if (detail.ValueKind == JsonValueKind.Array)
                {
                    return ValidationMessage(detail);
                }
                return detail.ToString();
            }
        }
        catch (JsonException)
        {
            // Fall through to the status-based message.
        }

        return $"{Tr[Copy.RequestFailed]} ({(int)response.StatusCode})";
    }

    /// <summary>
    /// FastAPI answers a 422 with an array of field paths and English messages.
    /// Viorela reads this screen, so the fields are named in her own words and the
    /// technical shape stays out of the interface.
    /// </summary>
    private string ValidationMessage(JsonElement detail)
    {
        var fields = new List<string>();
        foreach (var problem in detail.EnumerateArray())
        {
            if (!problem.TryGetProperty("loc", out var loc) || loc.ValueKind != JsonValueKind.Array)
            {
                continue;
            }
            var name = loc.EnumerateArray()
                .Where(part => part.ValueKind == JsonValueKind.String)
                .Select(part => part.GetString())
                .LastOrDefault(part => part is not null and not "body");
            var label = FieldLabel(name);
            if (label is not null && !fields.Contains(label))
            {
                fields.Add(label);
            }
        }

        return fields.Count == 0
            ? Tr[Copy.IncompleteData]
            : $"{Tr[Copy.StillMissing]}: {string.Join(", ", fields)}.";
    }

    private string? FieldLabel(string? name) => name switch
    {
        "title" => Tr.Pick("titlul", "the title"),
        "pillar" => Tr.Pick("pilonul", "the pillar"),
        "format" => Tr.Pick("formatul", "the format"),
        "hook" => Tr.Pick("hook-ul", "the hook"),
        "hook_type" => Tr.Pick("tipul de hook", "the hook type"),
        "script" => Tr.Pick("scriptul", "the script"),
        "caption" => Tr.Pick("captionul", "the caption"),
        "hashtags" => Tr.Pick(
            "hashtagurile (3–5, fiecare cu #)", "the hashtags (3–5, each with #)"),
        "cta" => Tr.Pick("CTA-ul", "the CTA"),
        "source" => Tr.Pick("sursa", "the source"),
        "content_blocks" => Tr.Pick("blocurile de conținut", "the content blocks"),
        "visual_direction" => Tr.Pick("direcția vizuală", "the visual direction"),
        "duration_or_count" => Tr.Pick(
            "durata sau numărul de cadre", "the duration or number of frames"),
        "format_details" => Tr.Pick("blocul de producție", "the production block"),
        "variant_ids" => Tr.Pick("variantele alese", "the chosen variants"),
        _ => name
    };
}

public sealed class StudioApiException(int statusCode, string message)
    : InvalidOperationException(message)
{
    public int StatusCode { get; } = statusCode;
}
