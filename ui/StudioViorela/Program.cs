using Microsoft.AspNetCore.Components.Web;
using Microsoft.AspNetCore.Components.WebAssembly.Hosting;
using StudioViorela;
using StudioViorela.Services;

var builder = WebAssemblyHostBuilder.CreateDefault(args);
builder.RootComponents.Add<App>("#app");
builder.RootComponents.Add<HeadOutlet>("head::after");

var configuredApi = builder.Configuration["ApiBaseUrl"];
var apiBase = string.IsNullOrWhiteSpace(configuredApi)
    ? builder.HostEnvironment.BaseAddress
    : configuredApi;

builder.Services.AddScoped(_ => new HttpClient { BaseAddress = new Uri(apiBase) });
builder.Services.AddScoped<StudioApiClient>();
builder.Services.AddScoped<GenerationEventStream>();
builder.Services.AddScoped<ChatEventStream>();
builder.Services.AddScoped<StudioContextState>();

await builder.Build().RunAsync();
