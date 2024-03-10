import os
import subprocess
import hashlib
import struct
import zlib
import time
from collections import namedtuple

IndexEntry = namedtuple('IndexEntry', [
    'ctime_s', 'ctime_n', 'mtime_s', 'mtime_n', 'dev', 'ino', 'mode',
    'uid', 'gid', 'size', 'sha1', 'flags', 'path',
])

def init(repo):
    print(f"Initializing repository: {repo}")
    """Create directory for repo and initialize .git directory."""
    os.mkdir(repo)
    os.mkdir(os.path.join(repo, '.git'))
    for name in ['objects', 'refs', 'refs/heads']:
        os.mkdir(os.path.join(repo, '.git', name))
    with open(os.path.join(repo, '.git', 'HEAD'), 'wb') as f:
        f.write(b'ref: refs/heads/master\n')
    print('Initialized empty repository: {}'.format(repo))

def write_file(path, data):
    print(f"Writing to file: {path}")
    """Helper function to write data to a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)

def read_file(path):
    print(f"Reading file: {path}")
    """Helper function to read data from a file."""
    with open(path, 'rb') as f:
        return f.read()

def hash_object(data, obj_type, write=True):
    print(f"Hashing {obj_type} object")
    """Compute hash of object data of given type and write to object store
    if "write" is True. Return SHA-1 object hash as hex string."""
    header = '{} {}'.format(obj_type, len(data)).encode()
    full_data = header + b'\x00' + data
    sha1 = hashlib.sha1(full_data).hexdigest()
    if write:
        path = os.path.join('.git', 'objects', sha1[:2], sha1[2:])
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_file(path, zlib.compress(full_data))
    return sha1

def read_index():
    print("Reading index")
    """Read git index file and return list of IndexEntry objects."""
    try:
        data = read_file(os.path.join('.git', 'index'))
    except FileNotFoundError:
        return []
    digest = hashlib.sha1(data[:-20]).digest()
    assert digest == data[-20:], 'invalid index checksum'
    signature, version, num_entries = struct.unpack('!4sLL', data[:12])
    assert signature == b'DIRC', \
            'invalid index signature {}'.format(signature)
    assert version == 2, 'unknown index version {}'.format(version)
    entry_data = data[12:-20]
    entries = []
    i = 0
    while i + 62 < len(entry_data):
        fields_end = i + 62
        fields = struct.unpack('!LLLLLLLLLL20sH',
                               entry_data[i:fields_end])
        path_end = entry_data.index(b'\x00', fields_end)
        path = entry_data[fields_end:path_end]
        entry = IndexEntry(*(fields + (path.decode(),)))
        entries.append(entry)
        entry_len = ((62 + len(path) + 8) // 8) * 8
        i += entry_len
    assert len(entries) == num_entries
    return entries

def write_tree():
    print("Writing tree object")
    """Write a tree object from the current index entries."""
    tree_entries = []
    for entry in read_index():
        assert '/' not in entry.path, \
                'currently only supports a single, top-level directory'
        mode_path = '{:o} {}'.format(entry.mode, entry.path).encode()
        tree_entry = mode_path + b'\x00' + entry.sha1
        tree_entries.append(tree_entry)
    return hash_object(b''.join(tree_entries), 'tree')

def add(file_path):
    print(f"Adding file to index: {file_path}")
    """Add a file to the Git index using the Git command line interface."""
    subprocess.run(['git', 'add', file_path], check=True)

def commit(message, author):
    print(f"Committing changes: {message} by {author}")
    """Commit the current state of the index to master with given message.
    Return hash of commit object.
    """
    tree = write_tree()
    parent = get_local_master_hash()
    timestamp = int(time.mktime(time.localtime()))
    utc_offset = -time.timezone
    author_time = '{} {}{:02}{:02}'.format(
            timestamp,
            '+' if utc_offset > 0 else '-',
            abs(utc_offset) // 3600,
            (abs(utc_offset) // 60) % 60)
    lines = ['tree ' + tree]
    if parent:
        lines.append('parent ' + parent)
    lines.append('author {} {}'.format(author, author_time))
    lines.append('committer {} {}'.format(author, author_time))
    lines.append('')
    lines.append(message)
    lines.append('')
    data = '\n'.join(lines).encode()
    sha1 = hash_object(data, 'commit')
    master_path = os.path.join('.git', 'refs', 'heads', 'master')
    write_file(master_path, (sha1 + '\n').encode())
    print('committed to master: {:7}'.format(sha1))
    return sha1

def get_local_master_hash():
    print("Getting local master hash")
    """Retrieve the SHA-1 hash of the last commit on the local master branch."""
    master_ref_path = os.path.join('.git', 'refs', 'heads', 'master')
    try:
        with open(master_ref_path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        print("Master branch not found. Have you committed yet?")
        return None


def extract_lines(data):
    print("Extracting lines from server data")
    """Extract list of lines from given server data."""
    lines = []
    i = 0
    for _ in range(1000):
        line_length = int(data[i:i + 4], 16)
        line = data[i + 4:i + line_length]
        lines.append(line)
        if line_length == 0:
            i += 4
        else:
            i += line_length
        if i >= len(data):
            break
    return lines

def build_lines_data(lines):
    print("Building lines data for server")
    """Build byte string from given lines to send to server."""
    result = []
    for line in lines:
        result.append('{:04x}'.format(len(line) + 5).encode())
        result.append(line)
        result.append(b'\n')
    result.append(b'0000')
    return b''.join(result)

import urllib.request

def http_request(url, username, password, data=None):
    print(f"Making HTTP request to: {url}")
    """Make an authenticated HTTP request to given URL (GET by default,
    POST if "data" is not None).
    """
    password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, url, username, password)
    auth_handler = urllib.request.HTTPBasicAuthHandler(password_manager)
    opener = urllib.request.build_opener(auth_handler)
    f = opener.open(url, data=data)
    return f.read()

def get_remote_master_hash(git_url, username, password):
    print(f"Getting remote master hash for: {git_url}")
    """Get commit hash of remote master branch, return SHA-1 hex string or
    None if no remote commits.
    """
    url = git_url + '/info/refs?service=git-receive-pack'
    response = http_request(url, username, password)
    lines = extract_lines(response)
    assert lines[0] == b'# service=git-receive-pack\n'
    assert lines[1] == b''
    if lines[2][:40] == b'0' * 40:
        return None
    master_sha1, master_ref = lines[2].split(b'\x00')[0].split()
    assert master_ref == b'refs/heads/master'
    assert len(master_sha1) == 40
    return master_sha1.decode()

def find_tree_objects(tree_sha1):
    print(f"Finding objects in tree: {tree_sha1}")
    """Return set of SHA-1 hashes of all objects in this tree
    (recursively), including the hash of the tree itself.
    """
    objects = {tree_sha1}
    for mode, path, sha1 in read_tree(sha1=tree_sha1):
        if stat.S_ISDIR(mode):
            objects.update(find_tree_objects(sha1))
        else:
            objects.add(sha1)
    return objects

def find_commit_objects(commit_sha1):
    print(f"Finding objects in commit: {commit_sha1}")
    """Return set of SHA-1 hashes of all objects in this commit
    (recursively), its tree, its parents, and the hash of the commit
    itself.
    """
    objects = {commit_sha1}
    obj_type, commit = read_object(commit_sha1)
    assert obj_type == 'commit'
    lines = commit.decode().splitlines()
    tree = next(l[5:45] for l in lines if l.startswith('tree '))
    objects.update(find_tree_objects(tree))
    parents = (l[7:47] for l in lines if l.startswith('parent '))
    for parent in parents:
        objects.update(find_commit_objects(parent))
    return objects

def find_missing_objects(local_sha1, remote_sha1):
    print("Finding missing objects for push")
    """Return set of SHA-1 hashes of objects in local commit that are
    missing at the remote (based on the given remote commit hash).
    """
    local_objects = find_commit_objects(local_sha1)
    if remote_sha1 is None:
        return local_objects
    remote_objects = find_commit_objects(remote_sha1)
    return local_objects - remote_objects

def encode_pack_object(obj):
    print(f"Encoding object for pack: {obj}")
    """Encode a single object for a pack file and return bytes
    (variable-length header followed by compressed data bytes).
    """
    obj_type, data = read_object(obj)
    type_num = ObjectType[obj_type].value
    size = len(data)
    byte = (type_num << 4) | (size & 0x0f)
    size >>= 4
    header = []
    while size:
        header.append(byte | 0x80)
        byte = size & 0x7f
        size >>= 7
    header.append(byte)
    return bytes(header) + zlib.compress(data)

def read_object(sha1):
    print(f"Reading Git object: {sha1}")
    """Read a Git object from .git/objects."""
    path = os.path.join('.git', 'objects', sha1[:2], sha1[2:])
    try:
        with open(path, 'rb') as f:
            data = zlib.decompress(f.read())
            # Splitting type and content
            x = data.find(b' ') + 1
            y = data.find(b'\x00', x)
            obj_type = data[:x-1].decode('ascii')
            content = data[y+1:]
            return obj_type, content
    except FileNotFoundError:
        print(f"Object {sha1} not found.")
        return None, None


def create_pack(objects):
    print("Creating pack file")
    """Create pack file containing all objects in given given set of
    SHA-1 hashes, return data bytes of full pack file.
    """
    header = struct.pack('!4sLL', b'PACK', 2, len(objects))
    body = b''.join(encode_pack_object(o) for o in sorted(objects))
    contents = header + body
    sha1 = hashlib.sha1(contents).digest()
    data = contents + sha1
    return data

def push(git_url, username, password):
    print(f"Pushing changes to: {git_url}")
    """Push master branch to given git repo URL."""
    remote_sha1 = get_remote_master_hash(git_url, username, password)
    local_sha1 = get_local_master_hash()
    missing = find_missing_objects(local_sha1, remote_sha1)
    lines = ['{} {} refs/heads/master\x00 report-status'.format(
            remote_sha1 or ('0' * 40), local_sha1).encode()]
    data = build_lines_data(lines) + create_pack(missing)
    url = git_url + '/git-receive-pack'
    response = http_request(url, username, password, data=data)
    lines = extract_lines(response)
    assert lines[0] == b'unpack ok\n', \
        "expected line 1 b'unpack ok', got: {}".format(lines[0])
