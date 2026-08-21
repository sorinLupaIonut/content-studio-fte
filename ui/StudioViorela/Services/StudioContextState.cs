using System.Text.Json;
using StudioViorela.Localization;
using StudioViorela.Models;

namespace StudioViorela.Services;

public sealed class StudioContextState(LanguageState language)
{
    private Translator T => language.Translator;

    private ChatTargetDto? _target;

    // What the label is *made of*, kept apart from the label itself. Storing
    // the finished string would freeze it in whichever language was on screen
    // when the target was set, and the open chat context would keep speaking
    // the old one after a switch.
    private string _subject = "";
    private string _hookType = "";

    /// <summary>The current chat target, labelled in the language on screen.</summary>
    public ChatTargetDto Target
    {
        get
        {
            var target = _target ?? ChatTargetDto.General();
            target.Label = Describe(target.Kind);
            return target;
        }
        private set => _target = value;
    }

    private string Describe(string kind) => kind switch
    {
        "generation_variant" => $"{_subject} · {HookLabel(_hookType)}",
        "saved_post" => $"{T[Copy.ChatSavedPrefix]} · {_subject}",
        _ => T[Copy.ChatGeneral]
    };

    public event Action? Changed;
    public event Func<string, Task>? GenerationPatched;
    public event Func<string, JsonElement, Task>? SavedPostPatched;

    public void SetGenerationVariant(
        string batchId,
        string ideaId,
        string ideaTitle,
        GenerationVariantDto variant)
    {
        _subject = ideaTitle;
        _hookType = variant.HookType;
        Target = new ChatTargetDto
        {
            Kind = "generation_variant",
            Id = variant.Id,
            BatchId = batchId,
            IdeaId = ideaId
        };
        Changed?.Invoke();
    }

    public void ClearGenerationVariant(string batchId)
    {
        if (Target.Kind != "generation_variant" || Target.BatchId != batchId)
        {
            return;
        }
        Target = ChatTargetDto.General();
        Changed?.Invoke();
    }

    public void SetSavedPost(SavedPostDto post)
    {
        _subject = post.Title;
        Target = new ChatTargetDto
        {
            Kind = "saved_post",
            Id = post.Id
        };
        Changed?.Invoke();
    }

    public void ClearSavedPost(string postId)
    {
        if (Target.Kind != "saved_post" || Target.Id != postId)
        {
            return;
        }
        Target = ChatTargetDto.General();
        Changed?.Invoke();
    }

    public async Task NotifyGenerationPatchedAsync(string variantId)
    {
        if (GenerationPatched is null)
        {
            return;
        }
        foreach (var handler in GenerationPatched.GetInvocationList()
                     .Cast<Func<string, Task>>())
        {
            await handler(variantId);
        }
    }

    /// <summary>
    /// A rewritten saved post arrives as content, not as a stored row: the server
    /// deliberately does not persist it. The editor holds it as a draft until she
    /// presses save and answers the gate.
    /// </summary>
    public async Task NotifySavedPostPatchedAsync(string postId, JsonElement content)
    {
        if (SavedPostPatched is null)
        {
            return;
        }
        foreach (var handler in SavedPostPatched.GetInvocationList()
                     .Cast<Func<string, JsonElement, Task>>())
        {
            await handler(postId, content);
        }
    }

    private string HookLabel(string value) => Values.HookLabel(T, value);
}
