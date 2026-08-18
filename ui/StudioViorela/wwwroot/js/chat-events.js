const streams = new Map();
let nextId = 1;

const eventNames = [
    "status",
    "text.delta",
    "ui.patch",
    "approval.required",
    "completed",
    "cancelled",
    "error",
    "heartbeat"
];

export function connect(url, dotnet) {
    const id = nextId++;
    const source = new EventSource(url);

    for (const eventName of eventNames) {
        source.addEventListener(eventName, event => {
            dotnet.invokeMethodAsync("OnEvent", eventName, event.data ?? "");
            if (["completed", "cancelled", "error", "approval.required"].includes(eventName)) {
                source.close();
                streams.delete(id);
            }
        });
    }

    source.onerror = () => {
        if (source.readyState !== EventSource.CLOSED) {
            dotnet.invokeMethodAsync("OnInterrupted");
        }
    };
    streams.set(id, source);
    return id;
}

export function disconnect(id) {
    const source = streams.get(id);
    if (source) {
        source.close();
        streams.delete(id);
    }
}
