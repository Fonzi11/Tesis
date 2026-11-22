using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Conecta las manos (reales u simuladas) con el modelo:
///  * pinza 1 mano: trasladar/rotar · pinza 2 manos: escalar/rotar/trasladar
///  * toque rápido izquierdo: pelar la capa externa · derecho: despiece
///  * pinza breve con ambas manos (sin moverlas): restablecer
/// En escritorio (sin visor) se puede usar teclado y ratón para las mismas
/// acciones: flechas/arrastre = rotar, WASD/QE = trasladar, +/- = escala,
/// L = pelar capa, U = mostrar todo, X = despiece, N = siguiente estudio,
/// R = restablecer.
/// </summary>
public sealed class NeuroHubGestureController : MonoBehaviour
{
    [SerializeField] private Transform studyRoot;
    [SerializeField] private NeuroHubStudyLoader loader;
    [SerializeField] private NeuroHubHandSource[] handSources;
    [SerializeField] private bool desktopControls = true;
    [SerializeField] private float rotationSpeed = 90f;
    [SerializeField] private float moveSpeed = 0.25f;

    private readonly NeuroHubGestureSolver solver = new();
    private Vector3 homePosition;
    private Quaternion homeRotation;
    private Vector3 homeScale;

    public NeuroHubGestureSolver Solver => solver;
    public Transform StudyRoot => studyRoot;

    public void Configure(Transform root, NeuroHubStudyLoader studyLoader, params NeuroHubHandSource[] sources)
    {
        studyRoot = root;
        loader = studyLoader;
        handSources = sources;
        CaptureHome();
    }

    private void Awake()
    {
        if (studyRoot == null) studyRoot = transform;
        CaptureHome();
        solver.Tap += OnTap;
        solver.TwoHandTap += ResetTransform;
    }

    private void OnDestroy()
    {
        solver.Tap -= OnTap;
        solver.TwoHandTap -= ResetTransform;
    }

    private void CaptureHome()
    {
        if (studyRoot == null) return;
        homePosition = studyRoot.position;
        homeRotation = studyRoot.rotation;
        homeScale = studyRoot.localScale;
        solver.ResetBaseScale(homeScale.x);
    }

    private void Update()
    {
        Step(Time.unscaledTime);
        if (desktopControls) DesktopInput(Time.unscaledDeltaTime);
    }

    /// <summary>Un paso de manipulación; público para las simulaciones.</summary>
    public void Step(float time)
    {
        NeuroHubHandState left = default, right = default;
        if (handSources != null)
        {
            foreach (NeuroHubHandSource source in handSources)
            {
                if (source == null || !source.isActiveAndEnabled) continue;
                source.GetHands(out NeuroHubHandState l, out NeuroHubHandState r);
                if (!left.tracked && l.tracked) left = l;
                if (!right.tracked && r.tracked) right = r;
            }
        }
        solver.Step(time, left, right, studyRoot);
    }

    private void OnTap(bool isLeft)
    {
        if (loader == null) return;
        if (isLeft) loader.PeelNextLayer();
        else loader.ToggleExplode();
    }

    public void ResetTransform()
    {
        studyRoot.SetPositionAndRotation(homePosition, homeRotation);
        studyRoot.localScale = homeScale;
        if (loader != null)
        {
            loader.ShowAllLayers();
            loader.SetExplodeImmediate(0f);
        }
    }

    private void DesktopInput(float dt)
    {
        Keyboard k = Keyboard.current;
        if (k != null)
        {
            Vector2 rot = Vector2.zero;
            if (k.leftArrowKey.isPressed) rot.x += 1;
            if (k.rightArrowKey.isPressed) rot.x -= 1;
            if (k.upArrowKey.isPressed) rot.y += 1;
            if (k.downArrowKey.isPressed) rot.y -= 1;
            studyRoot.Rotate(Vector3.up, rot.x * rotationSpeed * dt, Space.World);
            studyRoot.Rotate(Vector3.right, rot.y * rotationSpeed * dt, Space.World);

            Vector3 move = Vector3.zero;
            if (k.aKey.isPressed) move.x -= 1;
            if (k.dKey.isPressed) move.x += 1;
            if (k.wKey.isPressed) move.z += 1;
            if (k.sKey.isPressed) move.z -= 1;
            if (k.eKey.isPressed) move.y += 1;
            if (k.qKey.isPressed) move.y -= 1;
            studyRoot.position += move * moveSpeed * dt;

            float zoom = 0f;
            if (k.equalsKey.isPressed || k.numpadPlusKey.isPressed) zoom += 1;
            if (k.minusKey.isPressed || k.numpadMinusKey.isPressed) zoom -= 1;
            if (zoom != 0f)
            {
                float s = Mathf.Clamp(studyRoot.localScale.x * (1f + zoom * dt),
                    homeScale.x * solver.minScale, homeScale.x * solver.maxScale);
                studyRoot.localScale = Vector3.one * s;
            }

            if (loader != null)
            {
                if (k.lKey.wasPressedThisFrame) loader.PeelNextLayer();
                if (k.uKey.wasPressedThisFrame) loader.ShowAllLayers();
                if (k.xKey.wasPressedThisFrame) loader.ToggleExplode();
                if (k.nKey.wasPressedThisFrame) loader.LoadNextStudy();
            }
            if (k.rKey.wasPressedThisFrame) ResetTransform();
        }

        Mouse m = Mouse.current;
        if (m != null && m.leftButton.isPressed)
        {
            Vector2 d = m.delta.ReadValue();
            studyRoot.Rotate(Vector3.up, -d.x * 0.3f, Space.World);
            studyRoot.Rotate(Vector3.right, d.y * 0.3f, Space.World);
        }
        if (m != null)
        {
            float scroll = m.scroll.ReadValue().y;
            if (Mathf.Abs(scroll) > 0.01f)
            {
                float s = Mathf.Clamp(studyRoot.localScale.x * (1f + Mathf.Sign(scroll) * 0.05f),
                    homeScale.x * solver.minScale, homeScale.x * solver.maxScale);
                studyRoot.localScale = Vector3.one * s;
            }
        }
    }
}
