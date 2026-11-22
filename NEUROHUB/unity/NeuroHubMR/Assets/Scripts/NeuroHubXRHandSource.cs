using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.Hands;

/// <summary>
/// Manos reales mediante XR Hands sobre la extensión estándar
/// XR_EXT_hand_tracking de OpenXR (Quest, HoloLens 2, Pico, Magic Leap...).
/// No depende de ningún SDK propietario del fabricante del visor.
/// </summary>
public sealed class NeuroHubXRHandSource : NeuroHubHandSource
{
    [Tooltip("Espacio de seguimiento (Camera Offset del XR Origin).")]
    [SerializeField] private Transform trackingSpace;
    [Tooltip("Distancia pulgar-índice para iniciar la pinza (m).")]
    [SerializeField] private float pinchEnter = 0.022f;
    [Tooltip("Distancia pulgar-índice para soltar la pinza (m), con histéresis.")]
    [SerializeField] private float pinchExit = 0.035f;

    private static readonly List<XRHandSubsystem> Subsystems = new();
    private XRHandSubsystem subsystem;
    private bool leftPinch, rightPinch;

    public Transform TrackingSpace { get => trackingSpace; set => trackingSpace = value; }

    public override void GetHands(out NeuroHubHandState left, out NeuroHubHandState right)
    {
        left = default;
        right = default;
        if (subsystem == null || !subsystem.running)
        {
            Subsystems.Clear();
            SubsystemManager.GetSubsystems(Subsystems);
            subsystem = null;
            foreach (XRHandSubsystem s in Subsystems)
                if (s.running) { subsystem = s; break; }
            if (subsystem == null) return;
        }
        left = Read(subsystem.leftHand, ref leftPinch);
        right = Read(subsystem.rightHand, ref rightPinch);
    }

    private NeuroHubHandState Read(XRHand hand, ref bool pinchLatch)
    {
        NeuroHubHandState state = default;
        if (!hand.isTracked) { pinchLatch = false; return state; }
        if (!hand.GetJoint(XRHandJointID.ThumbTip).TryGetPose(out Pose thumb) ||
            !hand.GetJoint(XRHandJointID.IndexTip).TryGetPose(out Pose index))
            return state;
        Pose palm = hand.GetJoint(XRHandJointID.Palm).TryGetPose(out Pose p) ? p : hand.rootPose;

        float distance = Vector3.Distance(thumb.position, index.position);
        pinchLatch = pinchLatch ? distance < pinchExit : distance < pinchEnter;

        Vector3 mid = (thumb.position + index.position) * 0.5f;
        state.tracked = true;
        state.pinching = pinchLatch;
        state.pinchPosition = trackingSpace ? trackingSpace.TransformPoint(mid) : mid;
        state.rotation = trackingSpace ? trackingSpace.rotation * palm.rotation : palm.rotation;
        return state;
    }
}
