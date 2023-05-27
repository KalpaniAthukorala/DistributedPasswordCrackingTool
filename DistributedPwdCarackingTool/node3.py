from flask import Flask, request, jsonify
import re
from util import services_registration, get_ports_of_nodes, create_node_id, get_higher_nodes, election, \
    communicate_master, ready_for_election, get_details, check_health_of_the_service
from bully_algorithm import Bully
import threading
import time
import random
import sys
import requests
from multiprocessing import Value
import logging

counter = Value('i', 0)
app = Flask(__name__)


# verifying if port number and node name have been entered as command line arguments.
port_num = int(sys.argv[1])
assert port_num

node_name = sys.argv[2]
assert node_name

# saving the API logs to a file
logging.basicConfig(filename=f"logs/{node_name}.log", level=logging.INFO)

# an array to capture the messages that receive from acceptors
learner_result_array = []

node_id = create_node_id()
bully = Bully(node_name, node_id, port_num)

# register service in the Service Registry
service_register_status = services_registration(node_name, port_num, node_id)

def initialize_election(wait=True):
    '''
    Initialize the election process and check if there is an election in progress. If not, start the election and 
    proceed with the algorithm.
    '''
    if service_register_status == 200:
        ports_of_all_nodes = get_ports_of_nodes()
        del ports_of_all_nodes[node_name]

        # exchange node details with each node
        node_details = get_details(ports_of_all_nodes)

        if wait:
            timeout = random.randint(5, 15)
            time.sleep(timeout)
            print('timeouting in %s seconds' % timeout)

        # checks if there is an election on going
        election_ready = ready_for_election(ports_of_all_nodes, bully.election, bully.coordinator)
        if election_ready or not wait:
            print('Starting election in: %s' % node_name)
            bully.election = True
            higher_nodes_array = get_higher_nodes(node_details, node_id)
            print('higher node array', higher_nodes_array)
            if len(higher_nodes_array) == 0:
                bully.coordinator = True
                bully.election = False
                communicate_master(node_name)
                print('Coordinator is : %s' % node_name)
                print('**********End of election**********************')
                # Read all the passwords from the password.txt file
                with open("password.txt", "r") as f:
                    passwords = f.read().splitlines()

                # Ask the user for input password
                user_input = input("Enter your password: ")

                # Check if the input password matches any of the saved passwords
                if user_input in passwords:
                    print("Password is correct")
                else:
                    print("Incorrect password")
                    suggestions = generate_password_suggestions(user_input)
                    print("Suggested password must include %s" % suggestions)
                    suggest_passwords(passwords)
                    # Ask the user for input password
                    user_input = input("Enter your password: ")

                    # Check if the input password matches any of the saved passwords
                    if user_input in passwords:
                        print("Password is correct")

            else:
                election(higher_nodes_array, node_id)
    else:
        print('Service registration is not successful')


def suggest_passwords(passwords):
    '''
    Suggest alternative passwords based on the saved passwords.
    '''
    user_input = input("Enter your password: ")

    # Find the most similar password from the list
    most_similar_password = find_most_similar_password(user_input, passwords)

    if most_similar_password:
        print("Suggested passwords based on the most similar password '%s':" % most_similar_password)

    else:
        print("No similar passwords found. Please try a different password.")


def find_most_similar_password(user_input, passwords):
    '''
    Find the most similar password to the user input from the list of passwords.
    '''
    most_similar_password = None
    max_similarity_score = 0

    for password in passwords:
        similarity_score = calculate_similarity(user_input, password)
        if similarity_score > max_similarity_score:
            max_similarity_score = similarity_score
            most_similar_password = password

    return most_similar_password


def calculate_similarity(password1, password2):
    '''
    Calculate the similarity score between two passwords.
    '''
    # Example similarity calculation: Number of common letters divided by the total number of letters
    common_letters = len(set(password1) & set(password2))
    similarity_score = common_letters / max(len(password1), len(password2))
    return similarity_score


def generate_password_suggestions(password):
    '''
    Generate password suggestions based on the provided password.
    '''
    suggestions = []
    # Generate suggestions based on the provided password
    if not bool(re.search(r'[A-Z]', password)):
        suggestions.append("use capital letters")
    if not bool(re.search(r'[^a-zA-Z0-9]', password)):
        suggestions.append("use special characters")
    if not bool(re.search(r'[a-z]', password)):
        suggestions.append("use simple letters")
    return suggestions


# this api is used to exchange details with each node
@app.route('/nodeDetails', methods=['GET'])
def get_node_details():
    coordinator_bully = bully.coordinator
    node_id_bully = bully.node_id
    election_bully = bully.election
    node_name_bully = bully.node_name
    port_number_bully = bully.port
    return jsonify({'node_name': node_name_bully, 'node_id': node_id_bully, 'coordinator': coordinator_bully,
                    'election': election_bully, 'port': port_number_bully}), 200

#This API compares the ID of the incoming node with its own ID. If the incoming node's ID is greater than its own, the API executes the init method and sends an OK message to the sender. The execution then continues on the incoming node. Otherwise, the API does not execute any further actions.
@app.route('/response', methods=['POST'])
def response_node():
    data = request.get_json()
    incoming_node_id = data['node_id']
    self_node_id = bully.node_id
    if self_node_id > incoming_node_id:
        threading.Thread(target=initialize_election, args=[False]).start()
        bully.election = False
    return jsonify({'Response': 'OK'}), 200


# This API is used to announce the coordinator details.
@app.route('/announce', methods=['POST'])
def announce_coordinator():
    data = request.get_json()
    coordinator = data['coordinator']
    bully.coordinator = coordinator
    print('Coordinator is %s ' % coordinator)
    return jsonify({'response': 'OK'}), 200

#The proxy receives all election messages from nodes that are attempting to initiate an election. Since the init method should only be executed once, the proxy forwards only the first request it receives to the responseAPI. The responseAPI then executes the init method and sends an OK message back to the sender, signaling that the current node has been elected as the new leader.
@app.route('/proxy', methods=['POST'])
def proxy():
    with counter.get_lock():
        counter.value += 1
        unique_count = counter.value

    url = 'http://localhost:%s/response' % port_num
    if unique_count == 1:
        data = request.get_json()
        requests.post(url, json=data)

    return jsonify({'Response': 'OK'}), 200


# No node spends idle time, they always checks if the master node is alive in each 60 seconds.
def check_coordinator_health():
    threading.Timer(60.0, check_coordinator_health).start()
    health = check_health_of_the_service(bully.coordinator)
    if health == 'crashed':
        initialize_election()
    else:
        print('Coordinator is alive')


timer_thread1 = threading.Timer(15, initialize_election)
timer_thread1.start()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=port_num)
