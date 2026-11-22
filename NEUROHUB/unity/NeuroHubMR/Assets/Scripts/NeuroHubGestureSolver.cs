using System;
using UnityEngine;

/// <summary>
/// Lógica de manipulación gestual, independiente del visor y de Unity XR para
/// poder verificarla con manos simuladas.
///
/// Gestos:
///  * Pinza con una mano y mover: traslada y rota el modelo (agarre 6DoF).
///  * Pinza con las dos manos: escala (distancia entre manos), rota (vector
///    entre manos) y traslada (punto medio).
///  * Toque rápido (pinza breve sin desplazamiento): evento <see cref="Tap"/>
///    con la mano que lo hizo (izquierda: pelar capa; derecha: despiece).
/// </summary>
public sealed class NeuroHubGestureSolver
{
    public float minScale = 0.25f;
    public float maxScale = 4f;
    public float tapMaxSeconds = 0.35f;
    public float tapMaxMove = 0.015f;

    /// <summary>true = mano izquierda.</summary>
    public event Action<bool> Tap;
    /// <summary>Pinza breve con ambas manos y sin desplazamiento (restablecer).</summary>
    public event Action TwoHandTap;

    private struct HandTrack
    {
        public bool pinching;
        public float startTime;
        public Vector3 startPos;
        public Vector3 lastPos;
        public Quaternion lastRot;
        public bool usedForTwoHands;
    }

    private HandTrack l, r;
    private bool twoHands;
    private float twoHandsStartTime;
    private Vector3 twoStartL, twoStartR, twoLastL, twoLastR;
    private float startDist, startScale;
    private Vector3 startVec, startMid, startPos;
    private Quaternion startRot;
    private float baseScale = -1f;

    public void ResetBaseScale(float scale) => baseScale = scale;

    public void Step(float time, NeuroHubHandState left, NeuroHubHandState right, Transform target)
    {
        if (baseScale < 0f) baseScale = target.localScale.x;
        bool lp = left.tracked && left.pinching;
        bool rp = right.tracked && right.pinching;

        Begin(ref l, lp, left, time);
        Begin(ref r, rp, right, time);

        if (lp && rp)
        {
            Vector3 vec = right.pinchPosition - left.pinchPosition;
            Vector3 mid = (right.pinchPosition + left.pinchPosition) * 0.5f;
            if (!twoHands)
            {
                twoHands = true;
                startDist = Mathf.Max(vec.magnitude, 1e-4f);
                startScale = target.localScale.x;
                startVec = vec;
                startMid = mid;
                startPos = target.position;
                startRot = target.rotation;
                l.usedForTwoHands = r.usedForTwoHands = true;
                twoHandsStartTime = time;
                twoStartL = left.pinchPosition;
                twoStartR = right.pinchPosition;
            }
            twoLastL = left.pinchPosition;
            twoLastR = right.pinchPosition;
            float s = Mathf.Clamp(startScale * vec.magnitude / startDist,
                baseScale * minScale, baseScale * maxScale);
            Quaternion q = Quaternion.FromToRotation(startVec, vec);
            target.localScale = Vector3.one * s;
            target.rotation = q * startRot;
            target.position = mid + q * (startPos - startMid) * (s / startScale);
        }
        else
        {
            if (twoHands)
            {
                bool quick = time - twoHandsStartTime <= tapMaxSeconds;
                bool still = Vector3.Distance(twoStartL, twoLastL) <= tapMaxMove
                             && Vector3.Distance(twoStartR, twoLastR) <= tapMaxMove;
                if (quick && still) TwoHandTap?.Invoke();
            }
            twoHands = false;
            if (lp) Grab(ref l, left, target);
            else if (rp) Grab(ref r, right, target);
        }

        End(ref l, lp, left, time, true);
        End(ref r, rp, right, time, false);
        Remember(ref l, left);
        Remember(ref r, right);
    }

    private static void Begin(ref HandTrack h, bool pinching, NeuroHubHandState s, float time)
    {
        if (pinching && !h.pinching)
        {
            h.pinching = true;
            h.startTime = time;
            h.startPos = s.pinchPosition;
            h.lastPos = s.pinchPosition;
            h.lastRot = s.rotation;
            h.usedForTwoHands = false;
        }
    }

    private void End(ref HandTrack h, bool pinching, NeuroHubHandState s, float time, bool isLeft)
    {
        if (!pinching && h.pinching)
        {
            h.pinching = false;
            bool quick = time - h.startTime <= tapMaxSeconds;
            bool still = Vector3.Distance(h.lastPos, h.startPos) <= tapMaxMove;
            if (quick && still && !h.usedForTwoHands) Tap?.Invoke(isLeft);
        }
    }

    private static void Remember(ref HandTrack h, NeuroHubHandState s)
    {
        if (!h.pinching) return;
        h.lastPos = s.pinchPosition;
        h.lastRot = s.rotation;
    }

    private static void Grab(ref HandTrack h, NeuroHubHandState s, Transform target)
    {
        // Rotación alrededor del punto de pinza + traslación: el modelo sigue
        // a la mano como si estuviera sujeto entre los dedos.
        Quaternion dq = s.rotation * Quaternion.Inverse(h.lastRot);
        Vector3 pivot = h.lastPos;
        target.position = pivot + dq * (target.position - pivot) + (s.pinchPosition - h.lastPos);
        target.rotation = dq * target.rotation;
    }
}
