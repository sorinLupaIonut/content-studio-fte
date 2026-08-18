const streams = new Map();
let nextId = 1;

const eventTypes = [
    "status",
    "titles.ready",
    "idea.ready",
    "idea.failed",
    "completed",
    "cancelled",
    "error"
];

export function connect(url, dotnet) {
    const id = nextId++;
    const source = new EventSource(url, { withCredentials: true });

    for (const type of eventTypes) {
        source.addEventListener(type, event => {
            if (typeof event.data !== "string") {
                return;
            }
            dotnet.invokeMethodAsync("OnGenerationEvent", type);
            if (["completed", "cancelled", "error"].includes(type)) {
                source.close();
                streams.delete(id);
            }
        });
    }

    source.onerror = event => {
        if (typeof event.data !== "string") {
            dotnet.invokeMethodAsync("OnGenerationConnectionInterrupted");
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
