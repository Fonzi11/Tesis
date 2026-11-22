using UnityEngine;

/// <summary>Estado mínimo de una mano para la manipulación gestual.</summary>
public struct NeuroHubHandState
{
    public bool tracked;
    public bool pinching;
    /// <summary>Punto medio entre pulgar e índice, en coordenadas de mundo.</summary>
    public Vector3 pinchPosition;
    /// <summary>Orientación de la muñeca/palma, en coordenadas de mundo.</summary>
    public Quaternion rotation;
}

/// <summary>Origen de datos de manos: real (OpenXR) o simulado (pruebas).</summary>
public abstract class NeuroHubHandSource : MonoBehaviour
{
    public abstract void GetHands(out NeuroHubHandState left, out NeuroHubHandState right);
}
