using System.Text.Json;
using StudioViorela.Models;

namespace StudioViorela.Services;

public sealed class StudioContextState
{
    public ChatTargetDto Target { get; private set; } = ChatTargetDto.General();

    public event Action? Changed;
    public event Func<string, Task>? GenerationPatched;
    public event Func<string, JsonElement, Task>? SavedPostPatched;

    public void SetGenerationVariant(
        string batchId,
        string ideaId,
        string ideaTitle,
        GenerationVariantDto variant)
    {
        Target = new ChatTargetDto
        {
            Kind = "generation_variant",
            Id = variant.Id,
            BatchId = batchId,
            IdeaId = ideaId,
            Label = $"{ideaTitle} · {HookLabel(variant.HookType)}"
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
        Target = new ChatTargetDto
        {
            Kind = "saved_post",
            Id = post.Id,
            Label = $"Salvată · {post.Title}"
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

    private static string HookLabel(string value) => value switch
    {
        "PROVOCARE" => "Provocare",
        "CIFRA" => "Cifră",
        "SECRET" => "Secret",
        "INTREBARE" => "Întrebare",
        "CONTRAST" => "Contrast",
        _ => value
    };
}
