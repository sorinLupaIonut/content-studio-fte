using Microsoft.JSInterop;

namespace StudioViorela.Services;

public sealed class ChatEventStream(IJSRuntime js) : IAsyncDisposable
{
    private IJSObjectReference? _module;
    private DotNetObjectReference<ChatEventStream>? _self;
    private int? _streamId;

    public event Func<string, string, Task>? EventReceived;
    public event Func<Task>? ConnectionInterrupted;

    public async Task ConnectAsync(string url)
    {
        await DisconnectAsync();
        _module ??= await js.InvokeAsync<IJSObjectReference>(
            "import", "./js/chat-events.js");
        _self ??= DotNetObjectReference.Create(this);
        _streamId = await _module.InvokeAsync<int>("connect", url, _self);
    }

    [JSInvokable]
    public Task OnEvent(string eventType, string data) =>
        EventReceived?.Invoke(eventType, data) ?? Task.CompletedTask;

    [JSInvokable]
    public Task OnInterrupted() =>
        ConnectionInterrupted?.Invoke() ?? Task.CompletedTask;

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
