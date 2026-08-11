using System.Collections.Generic;
using System.Globalization;
using DotEAgent.Models;

namespace DotEAgent.Ipc
{
    /// <summary>
    /// Minimal .NET 3.5-compatible JSON deserializer for ActionCommand.
    /// Parses: strings, numbers (int/double), booleans, null, objects, arrays.
    /// No external dependencies.
    /// </summary>
    public static class JsonDeserializer
    {
        /// <summary>
        /// Deserializes a JSON string into an ActionCommand.
        /// Returns null if the JSON is malformed or missing required fields.
        /// </summary>
        public static ActionCommand DeserializeAction(string json)
        {
            if (string.IsNullOrEmpty(json))
                return null;

            object parsed = ParseValue(json, 0, out int _);
            Dictionary<string, object> root = parsed as Dictionary<string, object>;
            if (root == null)
                return null;

            ActionCommand cmd = new ActionCommand();

            object val;
            if (root.TryGetValue("command", out val) && val != null)
                cmd.Command = val.ToString();
            else
                return null; // command is required

            if (root.TryGetValue("parameters", out val) && val is Dictionary<string, object>)
                cmd.Parameters = (Dictionary<string, object>)val;

            if (root.TryGetValue("timestamp", out val) && val != null)
            {
                if (val is double)
                    cmd.Timestamp = (long)(double)val;
                else if (val is long)
                    cmd.Timestamp = (long)val;
                else if (val is int)
                    cmd.Timestamp = (int)val;
            }

            return cmd;
        }

        /// <summary>
        /// Serializes an ActionResult to JSON string for sending back to Python.
        /// </summary>
        public static string SerializeResult(ActionResult result)
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder(256);
            sb.Append("{\"success\":");
            sb.Append(result.Success ? "true" : "false");

            if (result.Error != null)
            {
                sb.Append(",\"error\":\"");
                AppendEscaped(sb, result.Error);
                sb.Append("\"");
            }
            else
            {
                sb.Append(",\"error\":null");
            }

            if (result.Metadata != null && result.Metadata.Count > 0)
            {
                sb.Append(",\"metadata\":{");
                bool first = true;
                foreach (KeyValuePair<string, object> kv in result.Metadata)
                {
                    if (!first) sb.Append(",");
                    first = false;
                    sb.Append("\"");
                    AppendEscaped(sb, kv.Key);
                    sb.Append("\":");
                    AppendValue(sb, kv.Value);
                }
                sb.Append("}");
            }
            else
            {
                sb.Append(",\"metadata\":null");
            }

            sb.Append("}");
            return sb.ToString();
        }

        // --- JSON Parser ---

        private static object ParseValue(string json, int index, out int endIndex)
        {
            index = SkipWhitespace(json, index);
            if (index >= json.Length)
            {
                endIndex = index;
                return null;
            }

            char c = json[index];
            if (c == '{')
                return ParseObject(json, index, out endIndex);
            if (c == '[')
                return ParseArray(json, index, out endIndex);
            if (c == '"')
                return ParseString(json, index, out endIndex);
            if (c == 't' || c == 'f')
                return ParseBool(json, index, out endIndex);
            if (c == 'n')
                return ParseNull(json, index, out endIndex);
            return ParseNumber(json, index, out endIndex);
        }

        private static Dictionary<string, object> ParseObject(string json, int index, out int endIndex)
        {
            Dictionary<string, object> dict = new Dictionary<string, object>();
            index++; // skip '{'
            index = SkipWhitespace(json, index);

            if (index < json.Length && json[index] == '}')
            {
                endIndex = index + 1;
                return dict;
            }

            while (index < json.Length)
            {
                index = SkipWhitespace(json, index);
                if (index >= json.Length || json[index] != '"')
                    break;

                string key = (string)ParseString(json, index, out index);
                index = SkipWhitespace(json, index);

                if (index >= json.Length || json[index] != ':')
                    break;
                index++; // skip ':'

                object value = ParseValue(json, index, out index);
                dict[key] = value;

                index = SkipWhitespace(json, index);
                if (index >= json.Length)
                    break;
                if (json[index] == ',')
                    index++;
                else if (json[index] == '}')
                    break;
            }

            endIndex = (index < json.Length && json[index] == '}') ? index + 1 : index;
            return dict;
        }

        private static List<object> ParseArray(string json, int index, out int endIndex)
        {
            List<object> list = new List<object>();
            index++; // skip '['
            index = SkipWhitespace(json, index);

            if (index < json.Length && json[index] == ']')
            {
                endIndex = index + 1;
                return list;
            }

            while (index < json.Length)
            {
                object value = ParseValue(json, index, out index);
                list.Add(value);

                index = SkipWhitespace(json, index);
                if (index >= json.Length)
                    break;
                if (json[index] == ',')
                    index++;
                else if (json[index] == ']')
                    break;
            }

            endIndex = (index < json.Length && json[index] == ']') ? index + 1 : index;
            return list;
        }

        private static string ParseString(string json, int index, out int endIndex)
        {
            index++; // skip opening '"'
            System.Text.StringBuilder sb = new System.Text.StringBuilder();

            while (index < json.Length)
            {
                char c = json[index];
                if (c == '"')
                {
                    endIndex = index + 1;
                    return sb.ToString();
                }
                if (c == '\\' && index + 1 < json.Length)
                {
                    index++;
                    char esc = json[index];
                    switch (esc)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (index + 4 < json.Length)
                            {
                                string hex = json.Substring(index + 1, 4);
                                int code;
                                if (int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out code))
                                    sb.Append((char)code);
                                index += 4;
                            }
                            break;
                        default: sb.Append(esc); break;
                    }
                }
                else
                {
                    sb.Append(c);
                }
                index++;
            }

            endIndex = index;
            return sb.ToString();
        }

        private static object ParseNumber(string json, int index, out int endIndex)
        {
            int start = index;
            bool isFloat = false;

            if (index < json.Length && (json[index] == '-' || json[index] == '+'))
                index++;

            while (index < json.Length && char.IsDigit(json[index]))
                index++;

            if (index < json.Length && json[index] == '.')
            {
                isFloat = true;
                index++;
                while (index < json.Length && char.IsDigit(json[index]))
                    index++;
            }

            if (index < json.Length && (json[index] == 'e' || json[index] == 'E'))
            {
                isFloat = true;
                index++;
                if (index < json.Length && (json[index] == '+' || json[index] == '-'))
                    index++;
                while (index < json.Length && char.IsDigit(json[index]))
                    index++;
            }

            endIndex = index;
            string numStr = json.Substring(start, index - start);

            if (isFloat)
            {
                double d;
                if (double.TryParse(numStr, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                    return d;
                return 0.0;
            }
            else
            {
                // Try int first, fall back to double for large numbers
                int i;
                if (int.TryParse(numStr, NumberStyles.Integer, CultureInfo.InvariantCulture, out i))
                    return i;
                long l;
                if (long.TryParse(numStr, NumberStyles.Integer, CultureInfo.InvariantCulture, out l))
                    return (double)l;
                double d;
                if (double.TryParse(numStr, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                    return d;
                return 0;
            }
        }

        private static object ParseBool(string json, int index, out int endIndex)
        {
            if (json.Length >= index + 4 && json.Substring(index, 4) == "true")
            {
                endIndex = index + 4;
                return true;
            }
            if (json.Length >= index + 5 && json.Substring(index, 5) == "false")
            {
                endIndex = index + 5;
                return false;
            }
            endIndex = index;
            return false;
        }

        private static object ParseNull(string json, int index, out int endIndex)
        {
            if (json.Length >= index + 4 && json.Substring(index, 4) == "null")
            {
                endIndex = index + 4;
                return null;
            }
            endIndex = index;
            return null;
        }

        private static int SkipWhitespace(string json, int index)
        {
            while (index < json.Length && (json[index] == ' ' || json[index] == '\t' || json[index] == '\n' || json[index] == '\r'))
                index++;
            return index;
        }

        // --- Serialization helpers for ActionResult ---

        private static void AppendEscaped(System.Text.StringBuilder sb, string value)
        {
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default: sb.Append(c); break;
                }
            }
        }

        private static void AppendValue(System.Text.StringBuilder sb, object value)
        {
            if (value == null)
            {
                sb.Append("null");
            }
            else if (value is bool)
            {
                sb.Append((bool)value ? "true" : "false");
            }
            else if (value is int)
            {
                sb.Append(((int)value).ToString(CultureInfo.InvariantCulture));
            }
            else if (value is long)
            {
                sb.Append(((long)value).ToString(CultureInfo.InvariantCulture));
            }
            else if (value is float)
            {
                sb.Append(((float)value).ToString(CultureInfo.InvariantCulture));
            }
            else if (value is double)
            {
                sb.Append(((double)value).ToString(CultureInfo.InvariantCulture));
            }
            else if (value is string)
            {
                sb.Append("\"");
                AppendEscaped(sb, (string)value);
                sb.Append("\"");
            }
            else
            {
                sb.Append("\"");
                AppendEscaped(sb, value.ToString());
                sb.Append("\"");
            }
        }
    }
}
