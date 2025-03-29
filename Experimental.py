import json
import os
import logging
from dotenv import load_dotenv
from simulator import Simulator
from scene import Scene
from openai_agent import OpenAIAgent
from typing import Any, Dict, List

# Load environment variables from the .env file
load_dotenv()

# API Key loaded once globally
api_key = os.getenv('OPENAI_API_KEY')

class Experimental:
    def __init__(self, scene_id: str, max_iterations: int = 5):
        """
        Initialize the Experimental class with a Scene ID.
        """
        self.max_iterations = max_iterations
        self.simulator = Simulator()  # Create Simulator object first
        self.scene = Scene(scene_id, self.simulator)  # Pass Simulator object into Scene constructor
        self.agent = OpenAIAgent(api_key)

        # Bind instance methods from self.simulator
        self.tool_mapping = {
            "render": self.simulator.render,
            "apply_force": self.simulator.apply_force,
            "get_velocity": self.simulator.get_velocity,
            "detect_collision": self.simulator.detect_collision,
            "get_parameters": self.simulator.get_parameters,
            "move_object": self.simulator.move_object,
            "get_position": self.simulator.get_position,
            "reset_sim": self.simulator.reset_sim,
            "step": self.simulator.step,
            "load_scene": self.simulator.load_scene,
        }

    def execute_tool_calls(self, tool_calls_json: str) -> List[Dict[str, Any]]:
        """Execute the provided tool calls and log the results."""
        tool_calls = json.loads(tool_calls_json)
        aggregated_results = []

        for call in tool_calls:
            tool = call['tool']
            params = call['parameters']
            result = None

            try:
                if tool in self.tool_mapping:  # Access instance-bound methods
                    func = self.tool_mapping[tool]
                    result = func(**params)  # Now calls methods directly
                else:
                    raise ValueError(f"Unknown tool '{tool}'")
            except Exception as e:
                logging.error(f"Exception during '{tool}': {str(e)}")
                result = {"error": str(e)}

            aggregated_results.append({
                "tool": tool,
                "parameters": params,
                "result": result,
                "sim_time": self.simulator.time  # Logging current timestep
            })

        return aggregated_results

    def extract_json_response(self, llm_output: str) -> str:
        """Extract JSON response from LLM's output."""
        try:
            json_start = llm_output.index("{")
            json_part = llm_output[json_start:]
            json_obj = json.loads(json_part)
            return json.dumps(json_obj.get("response", {}))  # Use .get() to avoid KeyError
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")
        except Exception as e:
            raise ValueError(f"Unexpected error: {e}")

    def run_experiment(self) -> Dict[str, Any]:
        """Run the experiment using the simulator and AI agent."""
        self.simulator.reset_sim()  # Reset the simulation
        correct_answer_found = False
        timeout_occurred = False

        # Get prompt and tool descriptions from the Scene
        scene_prompt = self.scene.get_prompt()
        tool_descriptions = self.scene.generate_tool_descriptions()
        full_prompt = f"{scene_prompt}\n\nAvailable Tools:\n{tool_descriptions}"

        results = []
        num_tool_calls = 0  # Initialize tool call counter
        for itr in range(self.max_iterations):
            # Only include previous results after the first iteration
            if itr == 0:
                user_input = f"{full_prompt}\nWhat should I do next?"
            else:
                user_input = f"{scene_prompt}\nPrevious Results: {json.dumps(results, indent=2)}\nWhat should I do next?"

            llm_response = self.agent.interact(user_input)

            try:
                tool_calls_json = self.extract_json_response(llm_response)
            except ValueError as e:
                logging.error(f"Error extracting JSON: {e}")
                # Return the error to LLM instead of breaking
                user_input = f"Error extracting the tool calls. Error: {e}\nWhat should I do next?"
                continue  # Continue the loop to ask the LLM again

            logging.info(f"\n=== Executing Tool Calls (Iteration {itr + 1}) ===")

            # Check if an answer is already provided before executing
            answer_found = False
            for call in tool_calls_json:
                if call['tool'] == 'answer':
                    final_answer = call['parameters'].get('answer')  # Use .get() to avoid KeyError
                    if final_answer is not None:
                        correct_answer = self.scene.get_correct_answer()
                        correct_answer_found = str(final_answer).strip().lower() == str(correct_answer).strip().lower()
                        answer_found = True
                    break  # Stop immediately if 'answer' tool was used

            # Execute the tool calls if no answer is found
            if not answer_found:
                results = self.execute_tool_calls(tool_calls_json)
                num_tool_calls += len(results)  # Update the tool call count after execution

                # Check again if an answer was provided
                for call in tool_calls_json:
                    if call['tool'] == 'answer':
                        final_answer = call['parameters'].get('answer')
                        if final_answer is not None:
                            correct_answer = self.scene.get_correct_answer()
                            correct_answer_found = str(final_answer).strip().lower() == str(correct_answer).strip().lower()
                        break

            # If an answer is found, break out of the loop
            if correct_answer_found:
                break  # Stop looping if we found a correct answer

        else:  # No break if answer not found
            timeout_occurred = True

        # Return the results of the experiment
        experiment_results = {
            'correct': correct_answer_found,
            'timeout': timeout_occurred,
            'num_tool_calls': num_tool_calls,  
            'iterations': itr + 1 if not timeout_occurred else self.max_iterations
        }
        return experiment_results
