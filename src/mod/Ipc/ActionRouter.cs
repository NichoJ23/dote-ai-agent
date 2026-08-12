using System.Collections.Generic;
using BepInEx.Logging;
using DotEAgent.Actions;
using DotEAgent.Models;

namespace DotEAgent.Ipc
{
    /// <summary>
    /// Polls the IPC bridge for incoming action commands, deserializes them,
    /// validates preconditions, routes to the appropriate handler, and sends
    /// the result back to the Python agent.
    /// </summary>
    public class ActionRouter
    {
        private static ManualLogSource Log { get { return Plugin.Log; } }

        private readonly IpcBridge bridge;
        private readonly Dictionary<string, IActionHandler> handlers;

        /// <summary>True if an action was received and processed this frame.</summary>
        public bool LastActionReceivedThisFrame { get; private set; }

        public ActionRouter(IpcBridge bridge)
        {
            this.bridge = bridge;
            this.handlers = new Dictionary<string, IActionHandler>();
        }

        /// <summary>Registers an action handler for its command type.</summary>
        public void RegisterHandler(IActionHandler handler)
        {
            handlers[handler.CommandType] = handler;
            Log.LogDebug("ActionRouter: registered handler for " + handler.CommandType);
        }

        /// <summary>
        /// Call each frame. Non-blocking poll for action commands.
        /// Processes at most one command per frame to avoid blocking the game loop.
        /// </summary>
        public void ProcessActions()
        {
            LastActionReceivedThisFrame = false;

            if (!bridge.IsActionConnected)
                return;

            string json = bridge.PollAction();
            if (json == null)
                return;

            LastActionReceivedThisFrame = true;

            // Deserialize
            ActionCommand command = JsonDeserializer.DeserializeAction(json);
            if (command == null)
            {
                Log.LogWarning("ActionRouter: failed to deserialize action command");
                ActionResult malformedResult = ActionResult.Fail("Malformed JSON: could not parse action command");
                SendResult(malformedResult);
                return;
            }

            Log.LogInfo("ActionRouter: received command " + command.Command);

            // Route to handler
            IActionHandler handler;
            if (!handlers.TryGetValue(command.Command, out handler))
            {
                string error = "Unknown command: " + command.Command;
                Log.LogWarning("ActionRouter: " + error);
                SendResult(ActionResult.Fail(error));
                return;
            }

            // Validate preconditions
            string preconditionError = handler.ValidatePreconditions(command);
            if (preconditionError != null)
            {
                Log.LogInfo("ActionRouter: precondition failed for " + command.Command + ": " + preconditionError);
                SendResult(ActionResult.Fail(preconditionError));
                return;
            }

            // Execute
            ActionResult result;
            try
            {
                result = handler.Execute(command);
            }
            catch (System.Exception ex)
            {
                Log.LogError("ActionRouter: exception executing " + command.Command + ": " + ex.Message);
                result = ActionResult.Fail("Internal error: " + ex.Message);
            }

            Log.LogInfo("ActionRouter: " + command.Command + " result: " + (result.Success ? "OK" : "FAIL - " + result.Error));
            SendResult(result);
        }

        private void SendResult(ActionResult result)
        {
            string json = JsonDeserializer.SerializeResult(result);
            bridge.SendResponse(json);
        }
    }
}
