using Microsoft.JSInterop;

namespace StudioViorela.Services;

public sealed class GenerationEventStream(IJSRuntime js) : IAsyncDisposable
{
    private IJSObjectReference? _module;
    private DotNetObjectReference<GenerationEventStream>? _self;
    private int? _streamId;

    public event Func<string, Task>? EventReceived;
    public event Func<Task>? ConnectionInterrupted;

    public async Task ConnectAsync(string url)
    {
        await DisconnectAsync();
        _module ??= await js.InvokeAsync<IJSObjectReference>(
            "import", "./js/generation-events.js");
        _self ??= DotNetObjectReference.Create(this);
        _streamId = await _module.InvokeAsync<int>("connect", url, _self);
    }

    [JSInvokable]
    public async Task OnGenerationEvent(string eventType)
    {
        if (EventReceived is not null)
        {
            await EventReceived.Invoke(eventType);
        }
    }

    [JSInvokable]
    public async Task OnGenerationConnectionInterrupted()
    {
        if (ConnectionInterrupted is not null)
        {
            await ConnectionInterrupted.Invoke();
        }
    }

    public async Task DisconnectAsync()
    {
        if (_module is not null && _streamId is not null)
        {
            await _module.InvokeVoidAsync("disconnect", _streamId.Value);
            _streamId = null;
        }
    }

    public async ValueTask DisposeAsync()
    {
        await DisconnectAsync();
        if (_module is not null)
        {
            await _module.DisposeAsync();
        }
        _self?.Dispose();
    }
}
