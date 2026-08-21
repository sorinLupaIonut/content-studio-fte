using System.Text.Json;
using System.Text.Json.Serialization;

namespace StudioViorela.Models;

public sealed class MeDto
{
    [JsonPropertyName("principal_id")]
    public string PrincipalId { get; set; } = "";

    [JsonPropertyName("email")]
    public string Email { get; set; } = "";

    [JsonPropertyName("provider")]
    public string Provider { get; set; } = "";

    [JsonPropertyName("is_development")]
    public bool IsDevelopment { get; set; }
}

public sealed class ProfileSectionsDto
{
    [JsonPropertyName("sections")]
    public List<ProfileSectionDto> Sections { get; set; } = [];
}

public sealed class ProfileSectionDto
{
    [JsonPropertyName("key")]
    public string Key { get; set; } = "";

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("group")]
    public string Group { get; set; } = "";

    [JsonPropertyName("blocks")]
    public List<ProfileBlockDto> Blocks { get; set; } = [];

    [JsonPropertyName("read_only")]
    public bool ReadOnly { get; set; }
}

public sealed class ProfileBlockDto
{
    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "paragraph";

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";
}

public sealed class ProfileUpdateDto
{
    [JsonPropertyName("blocks")]
    public List<ProfileBlockDto> Blocks { get; set; } = [];
}

public sealed class RunResponseDto
{
    [JsonPropertyName("run_id")]
    public string RunId { get; set; } = "";

    [JsonPropertyName("session_id")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("output")]
    public string? Output { get; set; }

    [JsonPropertyName("requests")]
    public List<ToolApprovalDto> Requests { get; set; } = [];
}

public sealed class ToolApprovalDto
{
    [JsonPropertyName("call_id")]
    public string CallId { get; set; } = "";

    [JsonPropertyName("tool_name")]
    public string ToolName { get; set; } = "";

    [JsonPropertyName("arguments")]
    public Dictionary<string, JsonElement> Arguments { get; set; } = [];
}

public sealed class DecisionsDto
{
    [JsonPropertyName("session_id")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("decisions")]
    public List<DecisionDto> Decisions { get; set; } = [];

    /// <summary>Interface language, which the agent answers and writes in.</summary>
    [JsonPropertyName("language")]
    public string Language { get; set; } = "ro";
}

public sealed class DecisionDto
{
    [JsonPropertyName("call_id")]
    public string CallId { get; set; } = "";

    [JsonPropertyName("approved")]
    public bool Approved { get; set; }

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";
}

public sealed class LibraryResponseDto
{
    [JsonPropertyName("items")]
    public List<LibraryItemDto> Items { get; set; } = [];
}

public sealed class LibraryItemDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("author")]
    public string? Author { get; set; }

    [JsonPropertyName("is_summary")]
    public bool IsSummary { get; set; }
}

public sealed class GenerationBatchEnvelopeDto
{
    [JsonPropertyName("batch")]
    public GenerationBatchDto? Batch { get; set; }
}

public sealed class GenerationBatchDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("pillar")]
    public string Pillar { get; set; } = "";

    [JsonPropertyName("format")]
    public string Format { get; set; } = "";

    [JsonPropertyName("focus")]
    public string? Focus { get; set; }

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("ideas")]
    public List<GenerationIdeaDto> Ideas { get; set; } = [];
}

public sealed class GenerationIdeaDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("ordinal")]
    public int Ordinal { get; set; }

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("angle")]
    public string Angle { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("retry_count")]
    public int RetryCount { get; set; }

    [JsonPropertyName("last_error")]
    public string? LastError { get; set; }

    [JsonPropertyName("variants")]
    public List<GenerationVariantDto> Variants { get; set; } = [];
}

public sealed class GenerationVariantDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("hook_type")]
    public string HookType { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("hook")]
    public string? Hook { get; set; }

    [JsonPropertyName("script")]
    public string? Script { get; set; }

    [JsonPropertyName("caption")]
    public string? Caption { get; set; }

    [JsonPropertyName("hashtags")]
    public List<string>? Hashtags { get; set; }

    [JsonPropertyName("cta")]
    public string? Cta { get; set; }

    [JsonPropertyName("source")]
    public string? Source { get; set; }

    [JsonPropertyName("format_details")]
    public FormatDetailsDto? FormatDetails { get; set; }

    [JsonPropertyName("is_selected")]
    public bool IsSelected { get; set; }
}

public sealed class FormatDetailsDto
{
    [JsonPropertyName("content_blocks")]
    public List<string> ContentBlocks { get; set; } = [];

    [JsonPropertyName("visual_direction")]
    public string VisualDirection { get; set; } = "";

    [JsonPropertyName("duration_or_count")]
    public string DurationOrCount { get; set; } = "";
}

public sealed class GenerationStartDto
{
    [JsonPropertyName("format")]
    public string Format { get; set; } = "Reel";

    [JsonPropertyName("pillar")]
    public string Pillar { get; set; } = "Educație";

    [JsonPropertyName("source")]
    public string Source { get; set; } = "Memorie";

    [JsonPropertyName("focus")]
    public string? Focus { get; set; }

    [JsonPropertyName("material_ids")]
    public List<string> MaterialIds { get; set; } = [];

    [JsonPropertyName("replace_current")]
    public bool ReplaceCurrent { get; set; }

    /// <summary>Interface language, which the agent answers and writes in.</summary>
    [JsonPropertyName("language")]
    public string Language { get; set; } = "ro";
}

public sealed class VariantSelectionDto
{
    [JsonPropertyName("selected")]
    public bool Selected { get; set; } = true;
}

public sealed class ChatTargetDto
{
    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "general";

    [JsonPropertyName("id")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Id { get; set; }

    [JsonIgnore]
    public string? BatchId { get; set; }

    [JsonIgnore]
    public string? IdeaId { get; set; }

    // Filled in by StudioContextState, which knows the language; this is the
    // value a target carries before anybody sets one.
    [JsonIgnore]
    public string Label { get; set; } = "";

    public static ChatTargetDto General() => new();
}

public sealed class ChatStartDto
{
    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("target")]
    public ChatTargetDto Target { get; set; } = ChatTargetDto.General();

    /// <summary>Interface language, which the agent answers and writes in.</summary>
    [JsonPropertyName("language")]
    public string Language { get; set; } = "ro";
}

public sealed class ChatAcceptedDto
{
    [JsonPropertyName("run_id")]
    public string RunId { get; set; } = "";

    [JsonPropertyName("session_id")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("target")]
    public ChatTargetDto Target { get; set; } = ChatTargetDto.General();
}

public sealed class StudioStreamEventDto
{
    [JsonPropertyName("sequence")]
    public int Sequence { get; set; }

    [JsonPropertyName("event")]
    public string Event { get; set; } = "";

    [JsonPropertyName("run_id")]
    public string? RunId { get; set; }

    [JsonPropertyName("payload")]
    public JsonElement Payload { get; set; }
}

public sealed class SavedPostsResponseDto
{
    [JsonPropertyName("items")]
    public List<SavedPostDto> Items { get; set; } = [];
}

public sealed class SavedPostEnvelopeDto
{
    [JsonPropertyName("post")]
    public SavedPostDto? Post { get; set; }
}

public sealed class SavedPostDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("posted_on")]
    public string PostedOn { get; set; } = "";

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("pillar")]
    public string Pillar { get; set; } = "";

    [JsonPropertyName("format")]
    public string Format { get; set; } = "";

    [JsonPropertyName("hook")]
    public string Hook { get; set; } = "";

    [JsonPropertyName("hook_type")]
    public string HookType { get; set; } = "";

    [JsonPropertyName("script")]
    public string Script { get; set; } = "";

    [JsonPropertyName("caption")]
    public string Caption { get; set; } = "";

    [JsonPropertyName("hashtags")]
    public List<string> Hashtags { get; set; } = [];

    [JsonPropertyName("cta")]
    public string Cta { get; set; } = "";

    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("format_details")]
    public FormatDetailsDto? FormatDetails { get; set; }
}

public sealed class SavePostsRequestDto
{
    [JsonPropertyName("variant_ids")]
    public List<string> VariantIds { get; set; } = [];
}

/// <summary>
/// The complete replacement draft for one saved post. Only the eleven content
/// fields: the harness contract forbids anything else, so `id` and `posted_on`
/// deliberately stay out of the request body.
///
/// `Script` and `FormatDetails` are nullable because a silent reel has neither:
/// she films without speaking and the caption carries what she would have said.
/// </summary>
public sealed class PostContentDto
{
    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("pillar")]
    public string Pillar { get; set; } = "";

    [JsonPropertyName("format")]
    public string Format { get; set; } = "";

    [JsonPropertyName("hook")]
    public string Hook { get; set; } = "";

    [JsonPropertyName("hook_type")]
    public string HookType { get; set; } = "";

    [JsonPropertyName("script")]
    public string? Script { get; set; }

    [JsonPropertyName("caption")]
    public string Caption { get; set; } = "";

    [JsonPropertyName("hashtags")]
    public List<string> Hashtags { get; set; } = [];

    [JsonPropertyName("cta")]
    public string Cta { get; set; } = "";

    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("format_details")]
    public FormatDetailsDto? FormatDetails { get; set; }
}
