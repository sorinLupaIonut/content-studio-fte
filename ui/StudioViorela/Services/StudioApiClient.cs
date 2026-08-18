using System.Net.Http.Json;
using System.Text.Json;
using StudioViorela.Models;

namespace StudioViorela.Services;

public sealed class StudioApiClient(HttpClient http)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public Task<MeDto> GetMeAsync() => GetAsync<MeDto>("api/me");

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
                }).ToList()
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
        GenerationStartDto request) =>
        PostAsync<GenerationStartDto, GenerationBatchEnvelopeDto>(
            "api/generation-batches", request);

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

    public Task<ChatAcceptedDto> StartChatAsync(ChatStartDto request) =>
        PostAsync<ChatStartDto, ChatAcceptedDto>("api/chat/runs", request);

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

    private static async Task<T> ReadAsync<T>(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode)
        {
            var detail = await ReadErrorAsync(response);
            throw new StudioApiException((int)response.StatusCode, detail);
        }

        return await response.Content.ReadFromJsonAsync<T>(Json)
            ?? throw new InvalidOperationException("Serverul a răspuns fără conținut.");
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode)
        {
            throw new StudioApiException(
                (int)response.StatusCode, await ReadErrorAsync(response));
        }
    }

    private static async Task<string> ReadErrorAsync(HttpResponseMessage response)
    {
        try
        {
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            if (document.RootElement.TryGetProperty("detail", out var detail))
            {
                if (detail.ValueKind == JsonValueKind.String)
                {
                    return detail.GetString() ?? "Cererea nu a reușit.";
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

        return $"Cererea nu a reușit ({(int)response.StatusCode}).";
    }

    /// <summary>
    /// FastAPI answers a 422 with an array of field paths and English messages.
    /// Viorela reads this screen, so the fields are named in her own words and the
    /// technical shape stays out of the interface.
    /// </summary>
    private static string ValidationMessage(JsonElement detail)
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
            ? "Datele trimise nu sunt complete."
            : $"Mai e de completat: {string.Join(", ", fields)}.";
    }

    private static string? FieldLabel(string? name) => name switch
    {
        "title" => "titlul",
        "pillar" => "pilonul",
        "format" => "formatul",
        "hook" => "hook-ul",
        "hook_type" => "tipul de hook",
        "script" => "scriptul",
        "caption" => "captionul",
        "hashtags" => "hashtagurile (3–5, fiecare cu #)",
        "cta" => "CTA-ul",
        "source" => "sursa",
        "content_blocks" => "blocurile de conținut",
        "visual_direction" => "direcția vizuală",
        "duration_or_count" => "durata sau numărul de cadre",
        "format_details" => "blocul de producție",
        "variant_ids" => "variantele alese",
        _ => name
    };
}

public sealed class StudioApiException(int statusCode, string message)
    : InvalidOperationException(message)
{
    public int StatusCode { get; } = statusCode;
}
