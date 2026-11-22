using UnityEngine;

/// <summary>
/// Manos simuladas: las pruebas (y el modo escritorio) escriben aquí las poses
/// que tendría un usuario real; el resto del sistema no distingue la diferencia.
/// </summary>
public sealed class NeuroHubSimulatedHandSource : NeuroHubHandSource
{
    public NeuroHubHandState left;
    public NeuroHubHandState right;

    public override void GetHands(out NeuroHubHandState l, out NeuroHubHandState r)
    {
        l = left;
        r = right;
    }

    public static NeuroHubHandState Hand(Vector3 position, bool pinching, Quaternion? rotation = null)
        => new NeuroHubHandState
        {
            tracked = true,
            pinching = pinching,
            pinchPosition = position,
            rotation = rotation ?? Quaternion.identity,
        };
}
