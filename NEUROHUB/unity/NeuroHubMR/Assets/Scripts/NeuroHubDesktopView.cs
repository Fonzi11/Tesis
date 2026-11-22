using System.Collections;
using UnityEngine;
using UnityEngine.InputSystem.XR;
using UnityEngine.XR;

/// <summary>
/// Vista de escritorio cuando no hay visor OpenXR activo (Editor sin runtime,
/// ejecutable en un PC sin gafas). Sin seguimiento, el TrackedPoseDriver deja la
/// cámara en el origen del suelo y el estudio queda fuera de cuadro; aquí se
/// desactiva y la cámara se coloca a la altura de los ojos mirando al estudio.
/// Con un visor activo no hace nada.
/// </summary>
public sealed class NeuroHubDesktopView : MonoBehaviour
{
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Boot() => new GameObject("ATLAS_VistaEscritorio").AddComponent<NeuroHubDesktopView>();

    private IEnumerator Start()
    {
        // El cargador de XR (InitManagerOnStart) intenta arrancar en los primeros cuadros.
        for (int i = 0; i < 10; i++) yield return null;
        if (XRSettings.isDeviceActive) { Destroy(gameObject); yield break; }

        Camera cam = Camera.main;
        NeuroHubStudyLoader loader = FindObjectOfType<NeuroHubStudyLoader>();
        if (cam == null || loader == null) yield break;
        if (cam.TryGetComponent(out TrackedPoseDriver driver)) driver.enabled = false;

        Vector3 target = loader.StudyRoot.position;
        cam.transform.position = target + new Vector3(0f, 0.12f, -0.50f);
        cam.transform.LookAt(target);
        cam.fieldOfView = 38f;
        cam.backgroundColor = new Color(0.07f, 0.08f, 0.10f, 1f);
        Debug.Log("ATLAS: sin visor activo, vista de escritorio.");
    }
}
