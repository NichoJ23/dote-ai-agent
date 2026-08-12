using System.Collections.Generic;
using Amplitude;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles RESEARCH command: queues a blueprint for research at the artifact.
    /// Requires an artifact on the floor that isn't already researching.
    /// 
    /// Parameters:
    ///   blueprint_name (string, required) - Name of the blueprint to research
    /// </summary>
    public class ResearchHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "RESEARCH"; } }

        public ResearchHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string bpName = command.GetString("blueprint_name");
            if (string.IsNullOrEmpty(bpName))
                return "Missing required parameter: blueprint_name";

            // Find artifact on the floor
            Artifact artifact = FindArtifact();
            if (artifact == null)
                return "No artifact found on the floor";

            if (!artifact.HealthCpnt.IsAlive())
                return "Artifact has been destroyed";

            if (artifact.ResearchedBP != null)
                return "Artifact is already researching: " + artifact.ResearchedBP.Name;

            // Validate blueprint exists
            BluePrintConfig bpConfig = Databases.GetDatabase<BluePrintConfig>(false).GetValue(bpName);
            if (bpConfig == null)
                return "Unknown blueprint: " + bpName;

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string bpName = command.GetString("blueprint_name");

            Artifact artifact = FindArtifact();
            BluePrintConfig bpConfig = Databases.GetDatabase<BluePrintConfig>(false).GetValue(bpName);

            // ResearchBluePrintByPlayer checks CanResearch, consumes science, sends RPCs
            bool success = artifact.ResearchBluePrintByPlayer(bpConfig);

            if (!success)
                return ActionResult.Fail("Research failed for " + bpName + " (insufficient science or not researchable)");

            var metadata = new Dictionary<string, object>();
            metadata["blueprint_name"] = bpName;

            return ActionResult.Ok(metadata);
        }

        /// <summary>Finds the artifact on the current floor by scanning rooms.</summary>
        private Artifact FindArtifact()
        {
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null || dungeon.OpenedRooms == null)
                return null;

            List<Room> rooms = dungeon.OpenedRooms;
            for (int i = 0; i < rooms.Count; i++)
            {
                Room room = rooms[i];
                if (room == null || room.MajorModule == null)
                    continue;

                Artifact artifact = room.MajorModule as Artifact;
                if (artifact != null)
                    return artifact;
            }
            return null;
        }
    }
}
