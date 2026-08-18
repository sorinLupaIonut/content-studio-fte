using System.Text.Json;
using StudioViorela.Models;

[assembly: Parallelize(Scope = ExecutionScope.MethodLevel)]

namespace StudioViorela.Tests;

[TestClass]
public sealed class ApiContractTests
{
    [TestMethod]
    public void StartRequestUsesThePythonFieldNames()
    {
        var json = JsonSerializer.Serialize(new GenerationStartDto
        {
            Format = "Reel",
            Pillar = "Educație",
            Source = "Memorie",
            ReplaceCurrent = true
        });

        StringAssert.Contains(json, "\"replace_current\":true");
        StringAssert.Contains(json, "\"material_ids\":[]");
    }

    [TestMethod]
    public void ReadyIdeaDeserializesItsFiveVariants()
    {
        var variants = Enumerable.Range(1, 5)
            .Select(index => $$"""
                {
                  "id": "variant-{{index}}",
                  "hook_type": "PROVOCARE",
                  "status": "ready",
                  "hook": "Hook",
                  "script": "Script",
                  "caption": "Caption",
                  "hashtags": ["#unu", "#doi", "#trei"],
                  "cta": "CTA",
                  "source": "Memorie",
                  "format_details": {
                    "content_blocks": ["Cadru"],
                    "visual_direction": "Cadru apropiat",
                    "duration_or_count": "30 secunde"
                  },
                  "is_selected": false
                }
                """)
            .ToArray();
        var json = $$"""
            {
              "id": "idea-1",
              "ordinal": 1,
              "title": "O idee",
              "angle": "Un unghi",
              "status": "ready",
              "retry_count": 0,
              "last_error": null,
              "variants": [{{string.Join(',', variants)}}]
            }
            """;

        var idea = JsonSerializer.Deserialize<GenerationIdeaDto>(json);

        Assert.IsNotNull(idea);
        Assert.HasCount(5, idea.Variants);
        Assert.AreEqual("30 secunde", idea.Variants[0].FormatDetails?.DurationOrCount);
    }

    [TestMethod]
    public void ChatRequestSendsOnlyTheTypedServerTarget()
    {
        var json = JsonSerializer.Serialize(new ChatStartDto
        {
            Message = "Scurtează hook-ul",
            Target = new ChatTargetDto
            {
                Kind = "generation_variant",
                Id = "33333333-3333-3333-3333-333333333333",
                BatchId = "browser-only-batch",
                Label = "browser-only-label"
            }
        });

        StringAssert.Contains(json, "\"kind\":\"generation_variant\"");
        StringAssert.Contains(json, "\"id\":\"33333333-3333-3333-3333-333333333333\"");
        Assert.IsFalse(json.Contains("browser-only-batch", StringComparison.Ordinal));
        Assert.IsFalse(json.Contains("browser-only-label", StringComparison.Ordinal));
    }

    [TestMethod]
    public void SaveRequestSendsOnlyTheVariantIds()
    {
        var json = JsonSerializer.Serialize(new SavePostsRequestDto
        {
            VariantIds = ["44444444-4444-4444-4444-444444444444"]
        });

        StringAssert.Contains(json, "\"variant_ids\":[\"44444444-4444-4444-4444-444444444444\"]");
    }

    [TestMethod]
    public void PostUpdateSendsOnlyTheElevenContentFields()
    {
        var json = JsonSerializer.Serialize(new PostContentDto
        {
            Title = "Titlu",
            Pillar = "Conexiune",
            Format = "Reel",
            Hook = "Hook",
            HookType = "INTREBARE",
            Script = "Script",
            Caption = "Caption",
            Hashtags = ["#unu", "#doi", "#trei"],
            Cta = "CTA",
            Source = "Memorie",
            FormatDetails = new FormatDetailsDto
            {
                ContentBlocks = ["Cadru"],
                VisualDirection = "Cadru apropiat",
                DurationOrCount = "30 secunde"
            }
        });

        using var document = JsonDocument.Parse(json);
        var fields = document.RootElement.EnumerateObject()
            .Select(property => property.Name)
            .ToArray();

        // The harness contract forbids extra fields, so an `id` or a `posted_on`
        // leaking in from the list response would fail the request with a 422.
        CollectionAssert.AreEquivalent(
            new[]
            {
                "title", "pillar", "format", "hook", "hook_type", "script",
                "caption", "hashtags", "cta", "source", "format_details"
            },
            fields);
    }

    [TestMethod]
    public void SilentReelPostSendsNullScriptAndNullProduction()
    {
        // A silent reel has no script and no production block. The two fields
        // still travel — as null, which the harness contract accepts — because
        // dropping them from the document would be a different shape again.
        var json = JsonSerializer.Serialize(new PostContentDto
        {
            Title = "Titlu",
            Pillar = "Conexiune",
            Format = "Reel",
            Hook = "Hook",
            HookType = "INTREBARE",
            Caption = "Un caption lung, care duce tot ce ar fi fost spus.",
            Hashtags = ["#unu", "#doi", "#trei"],
            Cta = "CTA",
            Source = "Memorie"
        });

        using var document = JsonDocument.Parse(json);

        Assert.AreEqual(JsonValueKind.Null, document.RootElement.GetProperty("script").ValueKind);
        Assert.AreEqual(
            JsonValueKind.Null,
            document.RootElement.GetProperty("format_details").ValueKind);
    }

    [TestMethod]
    public void SavedPostDeserializesItsProductionBlock()
    {
        var json = """
            {
              "id": "33333333-3333-3333-3333-333333333333",
              "posted_on": "2026-08-18",
              "title": "O postare",
              "pillar": "Conexiune",
              "format": "Reel",
              "hook": "Hook",
              "hook_type": "CIFRA",
              "script": "Script",
              "caption": "Caption",
              "hashtags": ["#unu", "#doi", "#trei"],
              "cta": "CTA",
              "source": "Memorie",
              "format_details": {
                "content_blocks": ["Cadru 1", "Cadru 2"],
                "visual_direction": "Lumină naturală",
                "duration_or_count": "35 secunde"
              },
              "status": "draft"
            }
            """;

        var post = JsonSerializer.Deserialize<SavedPostDto>(json);

        Assert.IsNotNull(post);
        Assert.AreEqual("CIFRA", post.HookType);
        Assert.HasCount(2, post.FormatDetails!.ContentBlocks);
    }
}
