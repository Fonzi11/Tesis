#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Abre la escena MR y entra en Play con o sin el recorrido de demostración.
/// También sirve desde la línea de comandos sin batchmode:
///   Unity.exe -projectPath ... -executeMethod NeuroHubDemoMenu.OpenAndPlay -atlas-demo
/// </summary>
[InitializeOnLoad]
public static class NeuroHubDemoMenu
{
    static NeuroHubDemoMenu()
    {
        // La bandera del menú vale para una sola sesión de Play.
        EditorApplication.playModeStateChanged += state =>
        {
            if (state == PlayModeStateChange.EnteredEditMode) PlayerPrefs.SetInt(NeuroHubDemoTour.EditorPrefKey, 0);
        };
    }

    [MenuItem("ATLAS/MR/Reproducir demostración (gestos simulados)")]
    public static void PlayDemo()
    {
        PlayerPrefs.SetInt(NeuroHubDemoTour.EditorPrefKey, 1);
        OpenAndPlay();
    }

    [MenuItem("ATLAS/MR/Abrir escena y entrar en Play")]
    public static void OpenAndPlay()
    {
        if (EditorApplication.isPlaying) return;
        if (EditorSceneManager.GetActiveScene().path != NeuroHubSceneBuilder.ScenePath)
            EditorSceneManager.OpenScene(NeuroHubSceneBuilder.ScenePath, OpenSceneMode.Single);
        EditorApplication.delayCall += () =>
        {
            GameObject study = GameObject.Find("ATLAS/Estudio");
            if (study != null)
            {
                Selection.activeGameObject = study;
                SceneView view = SceneView.lastActiveSceneView;
                if (view != null) view.LookAt(study.transform.position, Quaternion.Euler(20f, 200f, 0f), 0.35f);
            }
            EditorApplication.isPlaying = true;
            EditorApplication.delayCall += FitGameView;
        };
    }

    /// <summary>Vista de juego a escala 1 (que no recorte los rótulos).</summary>
    private static void FitGameView()
    {
        try
        {
            System.Type type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
            if (type == null) return;
            EditorWindow view = EditorWindow.GetWindow(type);
            type.GetMethod("SnapZoom", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                ?.Invoke(view, new object[] { 1f });
            view.Repaint();
        }
        catch (System.Exception error)
        {
            Debug.LogWarning("ATLAS: no se pudo ajustar la vista de juego: " + error.Message);
        }
    }
}
#endif
