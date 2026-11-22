using System.Collections.Generic;
using UnityEngine;

/// <summary>Estadística de tiempos de cuadro (requerimiento RD4: ≥ 30 FPS).</summary>
public sealed class NeuroHubPerformanceMonitor : MonoBehaviour
{
    [SerializeField] private int window = 300;
    private readonly Queue<float> samples = new();

    public float AverageFps { get; private set; }
    public float OnePercentLowFps { get; private set; }

    private void Update() => Add(Time.unscaledDeltaTime);

    public void Add(float frameSeconds)
    {
        samples.Enqueue(frameSeconds);
        while (samples.Count > window) samples.Dequeue();
        float[] s = samples.ToArray();
        float sum = 0f;
        foreach (float v in s) sum += v;
        AverageFps = s.Length > 0 ? s.Length / Mathf.Max(sum, 1e-6f) : 0f;
        System.Array.Sort(s);
        int idx = Mathf.Clamp(Mathf.CeilToInt(s.Length * 0.99f) - 1, 0, Mathf.Max(0, s.Length - 1));
        OnePercentLowFps = s.Length > 0 ? 1f / Mathf.Max(s[idx], 1e-6f) : 0f;
    }
}
