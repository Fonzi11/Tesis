using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

[Serializable]
public class NeuroHubModel
{
    public string id;
    public string file;
    public string name;
    public string group;
    public float[] color;
    public float opacity = 1f;
    public float volumeCm3;
    public int triangles;
}

[Serializable]
public class NeuroHubRenderProfile
{
    public string pipeline;
    public int antiAliasing;
    public bool gpuInstancing;
    public bool asyncLoad;
}

[Serializable]
public class NeuroHubStudyManifest
{
    public string schema;
    public string studyId;
    public string caseId;
    public string lesionType;
    public string lod;
    public bool clinicalReviewRequired;
    public NeuroHubModel[] models;
    public NeuroHubRenderProfile renderProfile;
}

[Serializable]
public class NeuroHubStudyIndex
{
    public string[] studies;
    public string[] lightStudies;
}

/// <summary>
/// Carga un estudio (FBX por estructura + manifiesto) bajo <see cref="studyRoot"/>,
/// aplica color y transparencia, y ofrece la visibilidad por capas y el
/// despiece ("explode") que pide la interfaz de realidad mixta.
/// </summary>
public sealed class NeuroHubStudyLoader : MonoBehaviour
{
    /// <summary>Orden de pelado: de la capa más externa a la más interna.</summary>
    public static readonly string[] PeelOrder =
    {
        "craneo", "corteza", "sustancia_blanca", "cerebelo_tronco",
        "ventriculos", "profundas", "vasos",
    };

    [SerializeField] public string studyId = "";
    [SerializeField] private Transform studyRoot;
    [SerializeField] private Material fallbackMaterial;
    [SerializeField] private bool loadOnStart = true;
    [Tooltip("Separación máxima del despiece, en metros (tamaño real).")]
    [SerializeField] private float explodeDistance = 0.06f;

    private readonly Dictionary<string, GameObject> loaded = new();
    private readonly Dictionary<string, NeuroHubModel> modelData = new();
    private readonly Dictionary<string, Vector3> explodeDirection = new();
    private float explodeTarget, explodeCurrent;
    private string[] index = Array.Empty<string>();

    public IReadOnlyDictionary<string, GameObject> LoadedModels => loaded;
    public NeuroHubStudyManifest Manifest { get; private set; }
    public bool IsLoading { get; private set; }
    public float Explode => explodeCurrent;
    public Transform StudyRoot => studyRoot != null ? studyRoot : transform;
    public string[] StudyIndex => index;
    public event Action<NeuroHubStudyManifest> StudyLoaded;

    private void Awake()
    {
        if (studyRoot == null) studyRoot = transform;
        if (fallbackMaterial == null)
            fallbackMaterial = Resources.Load<Material>("NeuroHub/NeuroHubTransparent");
        TextAsset idx = Resources.Load<TextAsset>("Studies/studies_index");
        if (idx != null) index = JsonUtility.FromJson<NeuroHubStudyIndex>(idx.text).studies ?? index;
        if (string.IsNullOrWhiteSpace(studyId) && index.Length > 0) studyId = index[0];
    }

    private void Start()
    {
        if (loadOnStart) StartCoroutine(LoadStudy(studyId));
    }

    private void Update()
    {
        if (Mathf.Approximately(explodeCurrent, explodeTarget)) return;
        explodeCurrent = Mathf.MoveTowards(explodeCurrent, explodeTarget, Time.unscaledDeltaTime * 2.5f);
        ApplyExplode();
    }

    public IEnumerator LoadStudy(string requestedStudyId)
    {
        IsLoading = true;
        ClearStudy();
        string id = string.IsNullOrWhiteSpace(requestedStudyId) ? studyId : requestedStudyId;
        TextAsset manifestAsset = Resources.Load<TextAsset>($"Studies/{id}/study_manifest");
        if (manifestAsset == null)
        {
            Debug.LogError($"ATLAS: no existe el manifiesto del estudio: Studies/{id}");
            IsLoading = false;
            yield break;
        }

        NeuroHubStudyManifest manifest;
        try { manifest = JsonUtility.FromJson<NeuroHubStudyManifest>(manifestAsset.text); }
        catch (Exception error)
        {
            Debug.LogError($"ATLAS: manifiesto inválido: {error.Message}");
            IsLoading = false;
            yield break;
        }

        foreach (NeuroHubModel model in manifest.models ?? Array.Empty<NeuroHubModel>())
        {
            string resourceKey = $"Studies/{id}/{Path.GetFileNameWithoutExtension(model.file)}";
            ResourceRequest request = Resources.LoadAsync<GameObject>(resourceKey);
            yield return request;
            if (request.asset is not GameObject prefab)
            {
                Debug.LogWarning($"ATLAS: {resourceKey} no está en Resources.");
                continue;
            }
            GameObject instance = Instantiate(prefab, StudyRoot, false);
            instance.name = model.id;
            ApplyMaterial(instance, model);
            loaded[model.id] = instance;
            modelData[model.id] = model;
        }

        studyId = id;
        Manifest = manifest;
        ComputeExplodeDirections();
        explodeCurrent = explodeTarget = 0f;
        IsLoading = false;
        Debug.Log($"ATLAS: estudio {id} cargado ({loaded.Count} estructuras, lesión: {manifest.lesionType}).");
        StudyLoaded?.Invoke(manifest);
    }

    public void LoadNextStudy()
    {
        if (index.Length == 0 || IsLoading) return;
        int i = Array.IndexOf(index, studyId);
        StartCoroutine(LoadStudy(index[(i + 1 + index.Length) % index.Length]));
    }

    public void ClearStudy()
    {
        foreach (GameObject model in loaded.Values)
            if (model != null) Destroy(model);
        loaded.Clear();
        modelData.Clear();
        explodeDirection.Clear();
    }

    // ---------------------------------------------------------------- capas
    public IEnumerable<string> GroupsPresent()
    {
        HashSet<string> seen = new();
        foreach (NeuroHubModel m in modelData.Values)
            if (seen.Add(m.group)) yield return m.group;
    }

    public bool IsGroupVisible(string group)
    {
        foreach (KeyValuePair<string, NeuroHubModel> kv in modelData)
            if (kv.Value.group == group && loaded[kv.Key].activeSelf) return true;
        return false;
    }

    public void SetGroupVisible(string group, bool visible)
    {
        foreach (KeyValuePair<string, NeuroHubModel> kv in modelData)
            if (kv.Value.group == group) loaded[kv.Key].SetActive(visible);
    }

    public void SetVisible(string modelId, bool visible)
    {
        if (loaded.TryGetValue(modelId, out GameObject model)) model.SetActive(visible);
    }

    /// <summary>
    /// Oculta la capa visible más externa. La lesión nunca se oculta: cuando ya
    /// no quedan capas por pelar, se restauran todas.
    /// </summary>
    public string PeelNextLayer()
    {
        HashSet<string> present = new(GroupsPresent());
        foreach (string group in PeelOrder)
        {
            if (!present.Contains(group) || !IsGroupVisible(group)) continue;
            SetGroupVisible(group, false);
            return group;
        }
        foreach (string group in present) SetGroupVisible(group, true);
        return null;
    }

    public void ShowAllLayers()
    {
        foreach (string group in new List<string>(GroupsPresent())) SetGroupVisible(group, true);
    }

    // ------------------------------------------------------------- despiece
    public void ToggleExplode() => explodeTarget = explodeTarget > 0.5f ? 0f : 1f;

    public void SetExplodeImmediate(float t)
    {
        explodeTarget = explodeCurrent = Mathf.Clamp01(t);
        ApplyExplode();
    }

    private void ComputeExplodeDirections()
    {
        // Centro del estudio = centro de la lesión (el despiece se abre a su
        // alrededor, que es lo que el residente necesita ver).
        Vector3 center = Vector3.zero;
        int n = 0;
        foreach (KeyValuePair<string, NeuroHubModel> kv in modelData)
        {
            if (kv.Value.group != "lesion") continue;
            center += LocalCenter(loaded[kv.Key]);
            n++;
        }
        if (n > 0) center /= n;
        foreach (KeyValuePair<string, GameObject> kv in loaded)
        {
            string group = modelData[kv.Key].group;
            if (group == "lesion" || group == "vasos")
            {
                explodeDirection[kv.Key] = Vector3.zero;
                continue;
            }
            Vector3 d = LocalCenter(kv.Value) - center;
            // Las capas externas se separan más que las profundas.
            int rank = Array.IndexOf(PeelOrder, group);
            float weight = rank < 0 ? 0.5f : 1f - rank / (float)PeelOrder.Length * 0.6f;
            explodeDirection[kv.Key] = (d.sqrMagnitude > 1e-8f ? d.normalized : Vector3.up) * weight;
        }
    }

    private Vector3 LocalCenter(GameObject go)
    {
        Vector3 sum = Vector3.zero;
        int n = 0;
        foreach (MeshFilter mf in go.GetComponentsInChildren<MeshFilter>(true))
        {
            if (mf.sharedMesh == null) continue;
            Vector3 world = mf.transform.TransformPoint(mf.sharedMesh.bounds.center);
            sum += StudyRoot.InverseTransformPoint(world);
            n++;
        }
        return n > 0 ? sum / n : go.transform.localPosition;
    }

    private void ApplyExplode()
    {
        foreach (KeyValuePair<string, GameObject> kv in loaded)
            if (explodeDirection.TryGetValue(kv.Key, out Vector3 d))
                kv.Value.transform.localPosition = d * (explodeDistance * explodeCurrent);
    }

    // ------------------------------------------------------------ material
    private void ApplyMaterial(GameObject model, NeuroHubModel data)
    {
        foreach (Renderer renderer in model.GetComponentsInChildren<Renderer>(true))
        {
            Material material = fallbackMaterial != null
                ? new Material(fallbackMaterial)
                : new Material(Shader.Find("Universal Render Pipeline/Lit"));
            float a = Mathf.Clamp01(data.opacity);
            Color c = data.color != null && data.color.Length >= 3
                ? new Color(data.color[0], data.color[1], data.color[2], a)
                : new Color(0.7f, 0.7f, 0.7f, a);
            material.SetColor("_BaseColor", c);
            material.SetFloat("_Smoothness", 0.45f);
            ConfigureTransparency(material, a);
            material.enableInstancing = true;
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
        }
    }

    private static void ConfigureTransparency(Material material, float opacity)
    {
        if (opacity >= 0.999f)
        {
            material.SetFloat("_Surface", 0f);
            material.SetFloat("_ZWrite", 1f);
            material.DisableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.SetOverrideTag("RenderType", "Opaque");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Geometry;
            return;
        }
        material.SetOverrideTag("RenderType", "Transparent");
        material.SetFloat("_Surface", 1f);
        material.SetFloat("_Blend", 0f); // Alpha (no premultiplicado)
        material.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
        material.SetFloat("_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        material.SetFloat("_SrcBlendAlpha", (float)UnityEngine.Rendering.BlendMode.One);
        material.SetFloat("_DstBlendAlpha", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        material.SetFloat("_ZWrite", 0f);
        material.SetFloat("_Cull", (float)UnityEngine.Rendering.CullMode.Back);
        material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
        material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
        // Las estructuras más opacas (profundas, lesión) se dibujan antes y las
        // envolturas muy translúcidas (cráneo, corteza) al final.
        material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent
                               + Mathf.RoundToInt((1f - opacity) * 50f);
    }
}
