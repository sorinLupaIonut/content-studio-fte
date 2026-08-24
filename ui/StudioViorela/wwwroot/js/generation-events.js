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
    // NO `withCredentials`, and that is the fix rather than an omission. The
    // API sets `allow_credentials=False` (harness/main.py), and a browser
    // refuses a credentialed cross-origin request whose response does not say
    // `Access-Control-Allow-Credentials: true` - so this stream simply never
    // connected in development, while chat's did, because chat never asked for
    // credentials either. It was invisible while details arrived on their own;
    // now that an idea is written when she opens it, this stream is how she
    // learns it is ready. In production both halves are same-origin, so nothing
    // is lost here.
    const source = new EventSource(url);

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
